'use strict';

// ============================================================
// GLOBAL STATE
// ============================================================

window.AppState = {
  suppliers: [],   // Φορτώνεται μία φορά στην εκκίνηση, cached για dropdowns
  machines: [],    // idem — Εισαγωγή + Συγχωνεύσεις το χρειάζονται και τα δύο
  categories: [],  // idem
  currentPage: null,
};

// ============================================================
// PYTHON BRIDGE
// ============================================================

async function pyCall(cmd, payload) {
  try {
    const r = await window.api.call(cmd, payload);
    if (!r.ok) { console.error(`[pyCall] ${cmd}:`, r.error); return null; }
    return r.result;
  } catch (e) {
    console.error(`[pyCall] ${cmd}:`, e.message);
    return null;
  }
}

async function pyCallStrict(cmd, payload) {
  const r = await window.api.call(cmd, payload);
  if (!r.ok) throw new Error(r.error || 'Άγνωστο σφάλμα');
  return r.result;
}
window.pyCall = pyCall;
window.pyCallStrict = pyCallStrict;

// ============================================================
// ΠΛΟΗΓΗΣΗ
// ============================================================

const Pages = {
  dashboard: { html: 'src/pages/dashboard/dashboard.html', js: 'src/pages/dashboard/dashboard.js' },
  invoices:  { html: 'src/pages/invoices/invoices.html',   js: 'src/pages/invoices/invoices.js' },
  suppliers: { html: 'src/pages/suppliers/suppliers.html', js: 'src/pages/suppliers/suppliers.js' },
  import:    { html: 'src/pages/import/import.html',       js: 'src/pages/import/import.js' },
  merges:    { html: 'src/pages/merges/merges.html',       js: 'src/pages/merges/merges.js' },
};

function loadFile(url) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.onload = () => {
      if (xhr.status === 200 || xhr.status === 0) resolve(xhr.responseText);
      else reject(new Error(`HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error('Network error'));
    xhr.send();
  });
}

async function navigateTo(pageId) {
  if (!Pages[pageId]) return;

  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector(`[data-page="${pageId}"]`)?.classList.add('active');
  window.AppState.currentPage = pageId;

  const container = document.getElementById('page-container');
  try {
    container.innerHTML = await loadFile(Pages[pageId].html);
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p>Σφάλμα φόρτωσης σελίδας: ${e.message}</p></div>`;
    return;
  }

  const oldScript = document.getElementById('page-script');
  if (oldScript) oldScript.remove();

  await new Promise(r => setTimeout(r, 30)); // wait for DOM render

  const script = document.createElement('script');
  script.id = 'page-script';
  script.type = 'module';
  script.src = Pages[pageId].js + '?v=' + Date.now();
  document.body.appendChild(script);
}
window.navigateTo = navigateTo;

// ============================================================
// TOAST + CONFIRM MODAL
// ============================================================

window.App = {
  toast(message, type = 'ok') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), type === 'ok' ? 2500 : 4500);
  },
  closeConfirm() {
    document.getElementById('confirm-modal').classList.remove('open');
    document.getElementById('confirm-ok-btn').onclick = null;
    document.getElementById('confirm-cancel-btn').onclick = null;
  },
  // onCancel προαιρετικό — π.χ. όταν το "Άκυρο" πρέπει να ανοίξει κάτι άλλο
  // (merge dialog) αντί να είναι αδιέξοδο.
  confirmDelete(msg, onOk, onCancel) {
    document.getElementById('confirm-msg').textContent = msg;
    document.getElementById('confirm-modal').classList.add('open');
    document.getElementById('confirm-ok-btn').onclick = () => { App.closeConfirm(); onOk(); };
    document.getElementById('confirm-cancel-btn').onclick = () => { App.closeConfirm(); if (onCancel) onCancel(); };
  },
};

// ============================================================
// STARTUP
// ============================================================

async function loadLookups() {
  window.AppState.suppliers = await pyCall('get_suppliers') || [];
  window.AppState.machines = await pyCall('list_machines') || [];
  window.AppState.categories = await pyCall('list_categories') || [];
}
window.reloadLookups = loadLookups;

async function startup() {
  await loadLookups();
  await navigateTo('import');
}

startup();
