'use strict';

import { escapeHtml } from './utils.js';

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
  pools:     { html: 'src/pages/pools/pools.html',         js: 'src/pages/pools/pools.js' },
  browse:    { html: 'src/pages/browse/browse.html',       js: 'src/pages/browse/browse.js' },
  explosives: { html: 'src/pages/explosives/explosives.html', js: 'src/pages/explosives/explosives.js' },
  suppliers: { html: 'src/pages/suppliers/suppliers.html', js: 'src/pages/suppliers/suppliers.js' },
  import:    { html: 'src/pages/import/import.html',       js: 'src/pages/import/import.js' },
  merges:    { html: 'src/pages/merges/merges.html',       js: 'src/pages/merges/merges.js' },
  settings:  { html: 'src/pages/settings/settings.html',   js: 'src/pages/settings/settings.js' },
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
  // Promise εκδοχή του confirmDelete — αντικαθιστά το native window.confirm(), που σε
  // Electron/Windows δεν επιστρέφει το keyboard focus στη σελίδα μετά το κλείσιμό του
  // (κανένα input δεν δέχεται πληκτρολόγηση μέχρι Alt+Tab). Μην ξαναχρησιμοποιήσεις
  // confirm()/alert() σε αυτό το app.
  confirmAsync(msg) {
    return new Promise(resolve => App.confirmDelete(msg, () => resolve(true), () => resolve(false)));
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

// ============================================================
// BACKUP-ON-CLOSE PROGRESS OVERLAY
// ============================================================
// Port από intake-tool/js/backup.js — ζει εδώ (όχι σε page module) γιατί το backup-on-close
// μπορεί να ενεργοποιηθεί ανεξάρτητα από ποια σελίδα είναι ανοιχτή τη στιγμή του κλεισίματος.
if (window.api?.onBackupProgress) {
  const bar = document.getElementById('bk-progress');
  const icon = document.getElementById('bk-progress-icon');
  const msg = document.getElementById('bk-progress-msg');
  const timerEl = document.getElementById('bk-progress-timer');
  const breakdownEl = document.getElementById('bk-progress-breakdown');
  const SLOW_THRESHOLD_SEC = 5;

  let tickHandle = null;
  let startedAt = null;

  function stopTicking() {
    if (tickHandle) { clearInterval(tickHandle); tickHandle = null; }
  }

  function fmtSec(s) {
    return s >= 60 ? `${Math.floor(s / 60)}λ ${Math.round(s % 60)}δ` : `${s.toFixed(1)}δ`;
  }

  window.api.onBackupProgress((status, data) => {
    bar.style.display = 'flex';
    if (status === 'start') {
      icon.textContent = '💾';
      msg.textContent = 'Γίνεται αντίγραφο ασφαλείας... παρακαλώ περιμένετε.';
      breakdownEl.textContent = '';
      startedAt = Date.now();
      stopTicking();
      timerEl.textContent = '0.0δ';
      tickHandle = setInterval(() => {
        timerEl.textContent = fmtSec((Date.now() - startedAt) / 1000);
      }, 100);
    } else if (status === 'done') {
      stopTicking();
      icon.textContent = '✅';
      msg.textContent = 'Το αντίγραφο ολοκληρώθηκε.';
      const total = data?.total_elapsed_sec ?? (startedAt ? (Date.now() - startedAt) / 1000 : null);
      timerEl.textContent = total != null ? fmtSec(total) : '';
      const results = data?.results || [];
      breakdownEl.innerHTML = results.map(r => {
        const sec = r.elapsed_sec ?? 0;
        const slow = sec >= SLOW_THRESHOLD_SEC;
        const label = r.skipped ? 'παραλείφθηκε (καμία αλλαγή)' : fmtSec(sec) + (slow ? ' — αργό' : '');
        return `<div${slow ? ' style="color:#ffb703;"' : ''}>${escapeHtml(r.folder)}: ${label}</div>`;
      }).join('');
    } else if (status === 'error') {
      stopTicking();
      icon.textContent = '⚠️';
      msg.textContent = 'Το αντίγραφο απέτυχε — κλείσιμο εφαρμογής.';
      const total = startedAt ? (Date.now() - startedAt) / 1000 : null;
      timerEl.textContent = total != null ? fmtSec(total) : '';
      breakdownEl.textContent = data?.error ? escapeHtml(data.error) : '';
    }
  });
}
