const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');
const fs = require('fs');

let mainWindow = null;
let pythonProcess = null;
let pendingRequests = {};
let reqCounter = 0;
let bridgeReady = false;
let queuedMessages = [];

// BACKEND_DIR is where the backend *code* lives (bridge.py, database.py) —
// this never changes. DATA_DIR is where the *data* (db, pdf_store) lives:
// the OS user-data dir once packaged, or next to the backend folder during
// unpackaged dev runs so it's easy to find/inspect/reset.
const BACKEND_DIR = path.join(__dirname, 'backend');
const DATA_DIR = app.isPackaged ? app.getPath('userData') : BACKEND_DIR;
// INVOICES_DB_PATH is the same override intake-tool and report-tool honour, so
// one launcher (intake-tool's launch-portable.ps1) can point all three at the
// same db, e.g. on the external drive. pdf_store always lives next to the db.
const DB_PATH = process.env.INVOICES_DB_PATH || path.join(DATA_DIR, 'invoicebook.db');
const PDF_STORE_DIR = path.join(path.dirname(DB_PATH), 'pdf_store');

// A missing db is NOT silently created empty when an explicit path was given or
// when running from the repo: on a fresh machine invoicebook.db doesn't come
// with the git clone, and a new empty db would have the user entering invoices
// into the wrong file without noticing. Only a packaged first run (userData)
// legitimately starts empty. INVOICEBOOK_ALLOW_NEW_DB=1 to start one on purpose.
function missingDbError() {
  const mustExist = !!process.env.INVOICES_DB_PATH || !app.isPackaged;
  if (!mustExist || process.env.INVOICEBOOK_ALLOW_NEW_DB === '1') return null;
  if (fs.existsSync(DB_PATH) && fs.statSync(DB_PATH).size > 0) return null;
  return `Δεν βρέθηκε η βάση τιμολογίων:\n\n${DB_PATH}\n\n` +
    'Δεν δημιουργείται αυτόματα νέα κενή βάση. Αν τα δεδομένα είναι σε φορητό δίσκο, ' +
    'ξεκίνα με το launch-portable.ps1 του intake-tool (-App invoicebook).\n' +
    'Για σκόπιμα νέα βάση: INVOICEBOOK_ALLOW_NEW_DB=1.';
}

function getPythonPath() {
  return os.platform() === 'win32' ? 'python' : 'python3';
}

function startBridge() {
  fs.mkdirSync(DATA_DIR, { recursive: true });

  const backendDir = BACKEND_DIR;
  const bridgeEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    INVOICEBOOK_DATA_DIR: DATA_DIR,
    INVOICES_DB_PATH: DB_PATH,
  };

  const cmd = getPythonPath();
  const args = [path.join(backendDir, 'bridge.py')];
  console.log(`[Bridge] Starting: ${cmd} ${args[0]} (db: ${DB_PATH})`);

  pythonProcess = spawn(cmd, args, {
    cwd: backendDir,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: bridgeEnv,
  });

  let buffer = '';
  pythonProcess.stdout.on('data', (data) => {
    buffer += data.toString();
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        if (msg.ready) {
          console.log('[Bridge] Ready');
          bridgeReady = true;
          for (const m of queuedMessages) pythonProcess.stdin.write(m + '\n');
          queuedMessages = [];
          continue;
        }
        const pending = pendingRequests[msg.id];
        if (pending) {
          delete pendingRequests[msg.id];
          if (msg.error) pending.reject(new Error(msg.error));
          else pending.resolve(msg.result);
        }
      } catch (e) {
        console.error('[Bridge] JSON parse error:', line);
      }
    }
  });

  pythonProcess.stderr.on('data', d => console.error('[Bridge ERR]', d.toString().trim()));
  pythonProcess.on('exit', (code) => {
    console.log(`[Bridge] Exited with code ${code}`);
    if (mainWindow && code !== 0) {
      dialog.showErrorBox('Σφάλμα', `Το Python process τερματίστηκε (κωδικός ${code}).`);
    }
  });
}

function callPython(cmd, payload = {}) {
  return new Promise((resolve, reject) => {
    const id = ++reqCounter;
    pendingRequests[id] = { resolve, reject };
    const msg = JSON.stringify({ id, cmd, payload });
    if (bridgeReady) pythonProcess.stdin.write(msg + '\n');
    else queuedMessages.push(msg);
    setTimeout(() => {
      if (pendingRequests[id]) {
        delete pendingRequests[id];
        reject(new Error(`Timeout: ${cmd}`));
      }
    }, 120000);
  });
}

// Πρέπει να μείνει συγχρονισμένο με τη λίστα `if cmd == '...'` του backend/bridge.py —
// αν προστεθεί νέα εντολή εκεί, πρέπει να προστεθεί και εδώ αλλιώς αποτυγχάνει σιωπηλά.
const ALLOWED_PYTHON_COMMANDS = new Set([
  'get_suppliers', 'add_supplier', 'update_supplier', 'delete_supplier',
  'get_invoices', 'get_invoice', 'add_invoice', 'update_invoice', 'delete_invoice',
  'attach_pdf',
  'import_staging_file', 'get_staging_batch', 'confirm_staging_row', 'reject_staging_row',
  'parse_import_file', 'stage_rows', 'list_categories', 'list_machines',
  'find_duplicate_invoice', 'merge_documents',
  'get_supplier_merge_candidates', 'get_supplier_merge_preview', 'merge_suppliers',
  'get_description_merge_candidates', 'merge_item_descriptions',
  'get_machine_merge_candidates', 'get_machine_merge_preview', 'merge_machines',
  'get_orphan_machines', 'delete_orphan_machines', 'get_single_supplier_plate_machines',
  'get_pdf_store_report', 'delete_orphan_pdfs', 'find_invoices_with_same_pdf',
  'dismiss_merge_candidate',
  'get_summary',
]);

function setupIPC() {
  ipcMain.handle('python', async (event, cmd, payload) => {
    if (!ALLOWED_PYTHON_COMMANDS.has(cmd)) {
      return { ok: false, error: `Άγνωστη εντολή: ${cmd}` };
    }
    try {
      return { ok: true, result: await callPython(cmd, payload) };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });

  ipcMain.handle('open-import-dialog', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
      filters: [{ name: 'CSV/JSON', extensions: ['csv', 'json'] }],
      properties: ['openFile'],
    });
    return canceled ? null : filePaths[0];
  });

  ipcMain.handle('open-pdf-dialog', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
      filters: [{ name: 'PDF', extensions: ['pdf'] }],
      properties: ['openFile'],
    });
    return canceled ? null : filePaths[0];
  });

  ipcMain.handle('open-stored-file', async (event, filename) => {
    const fullPath = path.join(PDF_STORE_DIR, filename);
    const err = await shell.openPath(fullPath);
    return err ? { ok: false, error: err } : { ok: true };
  });

  ipcMain.handle('open-local-file', async (event, filePath) => {
    const err = await shell.openPath(filePath);
    return err ? { ok: false, error: err } : { ok: true };
  });

  ipcMain.on('window-minimize', () => mainWindow?.minimize());
  ipcMain.on('window-maximize', () => {
    mainWindow?.isMaximized() ? mainWindow.unmaximize() : mainWindow?.maximize();
  });
  ipcMain.on('window-close', () => mainWindow?.close());
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280, height: 800,
    minWidth: 1024, minHeight: 700,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#0f2040',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
}

app.commandLine.appendSwitch('lang', 'el');

app.whenReady().then(() => {
  const dbError = missingDbError();
  if (dbError) {
    dialog.showErrorBox('Δεν βρέθηκε βάση', dbError);
    app.quit();
    return;
  }
  setupIPC();
  startBridge();
  createWindow();
});

app.on('window-all-closed', () => {
  if (pythonProcess) {
    pythonProcess.stdin.end();
    pythonProcess.kill('SIGTERM');
  }
  setTimeout(() => app.quit(), 300);
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
