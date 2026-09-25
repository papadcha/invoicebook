import { escapeHtml, _lock, attachAutocomplete } from '../../../js/utils.js';

// ── ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ ──────────────────────────────────────────────────────
// Port από intake-tool/js/backup.js (ήδη δουλεμένο εκεί, με backend/backup.py ήδη
// αντιγραμμένο στο invoicebook από τη Φάση 1 του backup-on-close). Το progress overlay
// κατά το κλείσιμο ζει στο js/main-app.js (global, όχι εδώ) — ήδη ported εκεί.

let currentPaths = [];
let currentRemotes = [];

function pathRowHtml(value) {
  return `
    <div class="picker-row" data-bk-path-row style="margin-bottom:8px;">
      <input type="text" data-bk-path-input placeholder="π.χ. D:\\Backups\\invoicebook, \\\\NAS\\share\\..., ή mega:invoicebook-backup" value="${escapeHtml(value || '')}" style="flex:1; min-width:280px;">
      <button type="button" class="btn btn-outline btn-sm" data-bk-pick>📁 Επιλογή</button>
      <span class="items-remove-btn" data-bk-remove-row title="Αφαίρεση">✕</span>
    </div>`;
}
attachAutocomplete(document.getElementById('bk-paths-list'), '[data-bk-path-input]', () => currentRemotes);

function wireRow(row) {
  row.querySelector('[data-bk-pick]').addEventListener('click', async () => {
    if (!window.api?.openDir) return;
    const dir = await window.api.openDir();
    if (dir) row.querySelector('[data-bk-path-input]').value = dir;
  });
  row.querySelector('[data-bk-remove-row]').addEventListener('click', () => row.remove());
}

function renderPathsList() {
  const el = document.getElementById('bk-paths-list');
  el.innerHTML = (currentPaths.length ? currentPaths : ['']).map(pathRowHtml).join('');
  el.querySelectorAll('[data-bk-path-row]').forEach(wireRow);
}

document.getElementById('bk-add-path-btn').addEventListener('click', () => {
  const list = document.getElementById('bk-paths-list');
  list.insertAdjacentHTML('beforeend', pathRowHtml(''));
  wireRow(list.lastElementChild);
});

function readPathsFromForm() {
  return Array.from(document.querySelectorAll('#bk-paths-list [data-bk-path-input]'))
    .map(inp => inp.value.trim())
    .filter(Boolean);
}

async function renderRemotesTable() {
  const el = document.getElementById('bk-remotes-table');
  try {
    const remotes = await pyCall('list_remotes_detail') || [];
    currentRemotes = remotes.map(r => r.remote);
    if (!remotes.length) {
      el.innerHTML = `<p class="muted-sm">Δεν υπάρχουν rclone remotes — πάτησε "+ Νέο Remote".</p>`;
      return;
    }
    const typeLabels = { mega: 'Mega', drive: 'Google Drive', dropbox: 'Dropbox', onedrive: 'OneDrive', s3: 'Amazon S3', b2: 'Backblaze B2' };
    el.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th>Όνομα</th><th>Πάροχος</th><th></th></tr></thead>
          <tbody>${remotes.map(r => `
            <tr>
              <td class="mono">${escapeHtml(r.remote)}</td>
              <td class="muted-sm">${escapeHtml(typeLabels[r.type] || r.type)}</td>
              <td><button class="btn btn-danger btn-sm" data-bk-del-remote="${escapeHtml(r.name)}">Διαγραφή</button></td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    el.querySelectorAll('[data-bk-del-remote]').forEach(btn => btn.addEventListener('click', () => {
      App.confirmDelete(`Διαγραφή remote "${btn.dataset.bkDelRemote}";`, async () => {
        const r = await pyCall('delete_remote', { name: btn.dataset.bkDelRemote });
        if (!r?.ok) { App.toast('Σφάλμα: ' + (r?.error || 'άγνωστο'), 'fail'); return; }
        renderRemotesTable();
      });
    }));
  } catch (e) {
    el.innerHTML = `<p style="color:var(--danger);">Σφάλμα: ${escapeHtml(e.message)}</p>`;
  }
}

document.getElementById('bk-new-remote-btn').addEventListener('click', async () => {
  if (!window.api?.openRcloneTerminal) return;
  const r = await window.api.openRcloneTerminal();
  if (!r.ok) { App.toast(r.error, 'fail'); return; }
  App.toast('Ρύθμισε το remote στο παράθυρο τερματικού που άνοιξε, μετά γύρνα εδώ.', 'ok');
});

async function renderHistory() {
  const el = document.getElementById('bk-history');
  const paths = readPathsFromForm();
  if (!paths.length) {
    el.innerHTML = `<p class="muted-sm">Όρισε τουλάχιστον έναν προορισμό για να δεις ιστορικό.</p>`;
    return;
  }
  el.innerHTML = paths.map(p => `<p class="muted-sm">Φόρτωση — ${escapeHtml(p)}...</p>`).join('');
  const sections = [];
  for (const p of paths) {
    let rows = '';
    try {
      const backups = await pyCallStrict('list_backups', { folder: p }) || [];
      if (!backups.length) {
        rows = `<tr><td colspan="3" class="muted-sm" style="text-align:center; padding:10px;">Δεν υπάρχουν αντίγραφα ακόμα</td></tr>`;
      } else {
        rows = backups.slice(0, 10).map(b => `
          <tr>
            <td class="mono">${escapeHtml(b.ts)}</td>
            <td class="muted-sm" style="text-align:right;">${b.size_kb} KB</td>
            <td style="text-align:right;"><button class="btn btn-outline btn-sm" data-bk-restore="${escapeHtml(b.path)}">Επαναφορά</button></td>
          </tr>`).join('');
      }
    } catch (e) {
      rows = `<tr><td colspan="3" style="color:var(--danger);">Σφάλμα: ${escapeHtml(e.message)}</td></tr>`;
    }
    sections.push(`
      <div style="margin-bottom:16px;">
        <p class="muted-sm" style="font-weight:600;">${escapeHtml(p)}</p>
        <div class="table-wrap">
          <table><thead><tr><th>Ημερομηνία</th><th></th><th></th></tr></thead><tbody>${rows}</tbody></table>
        </div>
      </div>`);
  }
  el.innerHTML = sections.join('');
  el.querySelectorAll('[data-bk-restore]').forEach(btn => btn.addEventListener('click', () => {
    const backupPath = btn.dataset.bkRestore;
    App.confirmDelete(
      `Επαναφορά από αυτό το αντίγραφο; Τα τρέχοντα δεδομένα θα αντικατασταθούν (κρατείται αυτόματο αντίγραφο ασφαλείας πριν, δεν αναιρείται μετά). Η εφαρμογή θα ξαναφορτωθεί.`,
      async () => {
        try {
          const r = await pyCallStrict('restore_backup', { path: backupPath });
          if (r.ok) {
            App.toast('✅ Επαναφορά ολοκληρώθηκε — επανεκκίνηση...', 'ok');
            setTimeout(() => window.location.reload(), 1200);
          }
        } catch (e) {
          App.toast('Σφάλμα επαναφοράς: ' + e.message, 'fail');
        }
      }
    );
  }));
}

async function renderPdfArchiveList() {
  const el = document.getElementById('bk-pdf-archive-list');
  const paths = readPathsFromForm();
  if (!paths.length) {
    el.innerHTML = `<p class="muted-sm">Όρισε τουλάχιστον έναν προορισμό για να δεις πλήρη αρχεία.</p>`;
    return;
  }
  const sections = [];
  for (const p of paths) {
    let rows = '';
    try {
      const archives = await pyCallStrict('list_pdf_archives', { folder: p }) || [];
      if (!archives.length) {
        rows = `<tr><td colspan="3" class="muted-sm" style="text-align:center; padding:10px;">Δεν υπάρχει πλήρες αρχείο ακόμα</td></tr>`;
      } else {
        rows = archives.map(a => `
          <tr>
            <td class="mono">${escapeHtml(a.ts)}</td>
            <td class="muted-sm" style="text-align:right;">${a.size_mb} MB</td>
            <td style="text-align:right;"><button class="btn btn-outline btn-sm" data-pdf-restore="${escapeHtml(a.path)}">Επαναφορά</button></td>
          </tr>`).join('');
      }
    } catch (e) {
      rows = `<tr><td colspan="3" style="color:var(--danger);">Σφάλμα: ${escapeHtml(e.message)}</td></tr>`;
    }
    sections.push(`
      <div style="margin-bottom:16px;">
        <p class="muted-sm" style="font-weight:600;">${escapeHtml(p)}</p>
        <div class="table-wrap">
          <table><thead><tr><th>Ημερομηνία</th><th></th><th></th></tr></thead><tbody>${rows}</tbody></table>
        </div>
      </div>`);
  }
  el.innerHTML = sections.join('');
  el.querySelectorAll('[data-pdf-restore]').forEach(btn => btn.addEventListener('click', () => {
    const archivePath = btn.dataset.pdfRestore;
    App.confirmDelete(
      `Επαναφορά ολόκληρου του pdf_store από αυτό το αρχείο; Ο τρέχων φάκελος pdf_store θα αντικατασταθεί (κρατείται σαν ".prerestore" δίπλα, δεν διαγράφεται αυτόματα). Η εφαρμογή θα ξαναφορτωθεί.`,
      async () => {
        try {
          const r = await pyCallStrict('restore_pdf_store', { path: archivePath });
          if (r.ok) {
            App.toast('✅ Επαναφορά pdf_store ολοκληρώθηκε — επανεκκίνηση...', 'ok');
            setTimeout(() => window.location.reload(), 1200);
          } else {
            App.toast('Σφάλμα επαναφοράς: ' + (r.error || 'άγνωστο'), 'fail');
          }
        } catch (e) {
          App.toast('Σφάλμα επαναφοράς: ' + e.message, 'fail');
        }
      }
    );
  }));
}

document.getElementById('bk-pdf-archive-now-btn').addEventListener('click', async () => {
  const btn = document.getElementById('bk-pdf-archive-now-btn');
  const unlock = _lock(btn);
  try {
    const r = await pyCallStrict('run_pdf_archive_now', {});
    const created = (r.results || []).filter(x => x.ok && x.path).length;
    const errs = (r.results || []).filter(x => !x.ok).map(x => x.error).join(' | ');
    if (errs) App.toast('Σφάλμα: ' + errs, 'fail');
    else App.toast(created ? `Δημιουργήθηκαν ${created} πλήρη αρχεία` : 'Ήδη ενημερωμένο, τίποτα νέο', 'ok');
    renderPdfArchiveList();
  } catch (e) {
    App.toast('Σφάλμα: ' + e.message, 'fail');
  } finally {
    unlock();
  }
});

document.getElementById('bk-save-btn').addEventListener('click', async () => {
  const paths = readPathsFromForm();
  const maxKeep = parseInt(document.getElementById('bk-maxkeep').value, 10) || 20;
  const unlock = _lock(document.getElementById('bk-save-btn'));
  try {
    await pyCallStrict('save_backup_config', { paths, max_keep: maxKeep });
    App.toast('Οι ρυθμίσεις αποθηκεύτηκαν', 'ok');
    document.getElementById('bk-maxkeep-label').textContent = maxKeep;
    renderHistory();
    renderPdfArchiveList();
  } catch (e) {
    App.toast('Σφάλμα: ' + e.message, 'fail');
  } finally {
    unlock();
  }
});

document.getElementById('bk-now-btn').addEventListener('click', async () => {
  const unlock = _lock(document.getElementById('bk-now-btn'));
  try {
    const r = await pyCallStrict('run_backup', {});
    if (r.ok) {
      const dur = r.total_elapsed_sec != null ? ` (${r.total_elapsed_sec}δ)` : '';
      App.toast('Backup ολοκληρώθηκε' + dur, 'ok');
    } else {
      const errs = (r.results || [])
        .flatMap(x => [x.db, x.pdf_store])
        .filter(x => x && !x.ok)
        .map(x => x.error)
        .join(' | ');
      App.toast('Σφάλμα backup: ' + (errs || r.error || 'άγνωστο'), 'fail');
    }
    renderLastStatus(await pyCall('get_backup_config'));
    renderHistory();
    renderPdfArchiveList();
  } catch (e) {
    App.toast('Σφάλμα: ' + e.message, 'fail');
  } finally {
    unlock();
  }
});

function renderLastStatus(cfg) {
  const el = document.getElementById('bk-last-status');
  if (!cfg?.last_backup) { el.style.display = 'none'; return; }
  const ok = cfg.last_status !== 'error';
  el.style.display = '';
  const dur = cfg.last_duration_sec != null ? ` (διάρκεια: ${cfg.last_duration_sec}δ)` : '';
  el.textContent = (ok ? '✅ ' : '⚠ ') + `Τελευταίο backup: ${cfg.last_backup}${dur}`;
  el.style.color = ok ? '' : 'var(--danger)';
}

async function renderManualSnapshots() {
  const el = document.getElementById('manual-snap-status');
  const warn = document.getElementById('manual-snap-warning');
  try {
    const s = await pyCallStrict('list_manual_snapshots', {});
    document.getElementById('manual-snap-keep-label').textContent = s.keep;
    el.textContent = s.count
      ? `${s.count} αρχεία, ${s.size_mb} MB — παλιότερο: ${s.oldest}, πιο πρόσφατο: ${s.newest}`
      : 'Κανένα αρχείο αυτή τη στιγμή.';
    warn.style.display = s.warn ? '' : 'none';
  } catch (e) {
    el.textContent = 'Σφάλμα: ' + e.message;
    warn.style.display = 'none';
  }
}

document.getElementById('manual-snap-clean-btn').addEventListener('click', async () => {
  const unlock = _lock(document.getElementById('manual-snap-clean-btn'));
  try {
    const r = await pyCallStrict('prune_manual_snapshots', {});
    App.toast(r.deleted ? `Διαγράφηκαν ${r.deleted} παλιά αντίγραφα` : 'Ήδη μέσα στο όριο, τίποτα να καθαριστεί', 'ok');
    await renderManualSnapshots();
  } catch (e) {
    App.toast('Σφάλμα: ' + e.message, 'fail');
  } finally {
    unlock();
  }
});

function renderEnabledState(enabled) {
  document.getElementById('bk-enabled').checked = enabled !== false;
  document.getElementById('bk-disabled-note').style.display = enabled === false ? '' : 'none';
}

document.getElementById('bk-enabled').addEventListener('change', async (e) => {
  const enabled = e.target.checked;
  try {
    await pyCallStrict('set_backup_enabled', { enabled });
    renderEnabledState(enabled);
    App.toast(enabled ? 'Backup-on-close ενεργό σε αυτό το μηχάνημα' : 'Backup-on-close απενεργοποιήθηκε σε αυτό το μηχάνημα', 'ok');
  } catch (err) {
    e.target.checked = !enabled;
    App.toast('Σφάλμα: ' + err.message, 'fail');
  }
});

async function loadBackupSettings() {
  const cfg = await pyCall('get_backup_config') || { paths: [], max_keep: 20 };
  currentPaths = cfg.paths || [];
  document.getElementById('bk-maxkeep').value = cfg.max_keep ?? 20;
  document.getElementById('bk-maxkeep-label').textContent = cfg.max_keep ?? 20;
  renderEnabledState(cfg.enabled);
  renderPathsList();
  renderLastStatus(cfg);
  await renderRemotesTable();
  await renderHistory();
  await renderPdfArchiveList();
  await renderManualSnapshots();
}

loadBackupSettings();
