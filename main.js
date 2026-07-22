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

// Dev mode only (v1): data lives next to the backend folder — same path
// bridge.py resolves via INVOICEBOOK_DATA_DIR below. Once packaged, both
// should point at app.getPath('userData') instead.
const BACKEND_DIR = path.join(__dirname, 'backend');
const PDF_STORE_DIR = path.join(BACKEND_DIR, 'pdf_store');

function getPythonPath() {
  return os.platform() === 'win32' ? 'python' : 'python3';
}

function startBridge() {
  const userDataDir = app.getPath('userData');
  fs.mkdirSync(userDataDir, { recursive: true });

  const backendDir = BACKEND_DIR;
  const bridgeEnv = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    // Dev mode only (v1): data lives next to the backend folder.
    // Once packaged, this should point at app.getPath('userData') instead.
    INVOICEBOOK_DATA_DIR: backendDir,
  };

  const cmd = getPythonPath();
  const args = [path.join(backendDir, 'bridge.py')];
  console.log(`[Bridge] Starting dev: ${cmd} ${args[0]}`);

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

  ipcMain.on('window-minimize', () => mainWindow?.minimize());
  ipcMain.on('window-maximize', () => {
    mainWindow?.isMaximized() ? mainWindow.unmaximize() : mainWindow?.maximize();
  });
  ipcMain.on('window-close', () => mainWindow?.close());
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440, height: 860,
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
