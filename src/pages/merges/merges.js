import { escapeHtml, _lock, normalizeGreek, attachAutocomplete } from '../../../js/utils.js';

// ── SUBTABS ──────────────────────────────────────────────────────────────────
const loaded = { suppliers: false, machines: false, descriptions: false };

document.querySelectorAll('.subtab[data-subtab]').forEach(btn => btn.addEventListener('click', () => {
  const tab = btn.dataset.subtab;
  document.querySelectorAll('.subtab[data-subtab]').forEach(b => b.classList.toggle('active', b === btn));
  document.querySelectorAll('.subtab-panel').forEach(p => p.style.display = (p.id === `panel-${tab}` ? '' : 'none'));
  if (tab === 'suppliers' && !loaded.suppliers) { loaded.suppliers = true; loadSupplierCandidates(); }
  if (tab === 'machines' && !loaded.machines) { loaded.machines = true; loadMachineCandidates(); loadOrphanMachines(); }
  if (tab === 'descriptions' && !loaded.descriptions) { loaded.descriptions = true; loadDescriptionCandidates(); }
}));

// ── ΓΕΝΙΚΟ MODAL ΠΡΟΕΠΙΣΚΟΠΗΣΗΣ/ΣΥΓΧΩΝΕΥΣΗΣ (προμηθευτές/μηχανήματα) ─────────
let pendingMerge = null; // { kind: 'supplier'|'machine', keepId, mergeId, onDone }

function openMergePreviewModal({ kind, keep, merge, keepId, mergeId, onDone }) {
  pendingMerge = { kind, keepId, mergeId, onDone };
  document.getElementById('merge-preview-title').textContent =
    kind === 'supplier' ? 'Προεπισκόπηση Συγχώνευσης Προμηθευτών' : 'Προεπισκόπηση Συγχώνευσης Μηχανημάτων';
  const body = document.getElementById('merge-preview-body');
  body.innerHTML = `<p>Θα κρατηθεί: <b>${escapeHtml(keep)}</b></p><p>Θα συγχωνευθεί και διαγραφεί: <b>${escapeHtml(merge)}</b></p><p class="muted-sm">Φόρτωση προεπισκόπησης…</p>`;
  document.getElementById('merge-preview-modal').classList.add('open');

  const previewCall = kind === 'supplier' ? 'get_supplier_merge_preview' : 'get_machine_merge_preview';
  pyCall(previewCall, { keep_id: keepId, merge_id: mergeId }).then(preview => {
    if (!preview) return;
    let extra = '';
    if (kind === 'supplier') {
      extra = `<p>${preview.invoice_count} τιμολόγι${preview.invoice_count === 1 ? 'ο' : 'α'} θα μεταφερθούν στον προμηθευτή που κρατιέται.</p>`;
    } else {
      extra = `<p>${preview.item_count} γραμμές τιμολογίων και ${preview.allocation_count} διαμοιρασμοί (Αποθέματα) θα μεταφερθούν.</p>`;
    }
    body.innerHTML = `<p>Θα κρατηθεί: <b>${escapeHtml(keep)}</b></p><p>Θα συγχωνευθεί και διαγραφεί: <b>${escapeHtml(merge)}</b></p>${extra}`;
  });
}

document.getElementById('merge-preview-cancel-btn').addEventListener('click', () => {
  document.getElementById('merge-preview-modal').classList.remove('open');
  pendingMerge = null;
});

document.getElementById('merge-preview-commit-btn').addEventListener('click', async () => {
  if (!pendingMerge) return;
  const { kind, keepId, mergeId, onDone } = pendingMerge;
  const btn = document.getElementById('merge-preview-commit-btn');
  const unlock = _lock(btn);
  try {
    const cmd = kind === 'supplier' ? 'merge_suppliers' : 'merge_machines';
    await pyCallStrict(cmd, { keep_id: keepId, merge_id: mergeId });
    App.toast('Η συγχώνευση ολοκληρώθηκε', 'ok');
    document.getElementById('merge-preview-modal').classList.remove('open');
    pendingMerge = null;
    window.reloadLookups();
    if (onDone) onDone();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

// ── ΠΡΟΜΗΘΕΥΤΕΣ ──────────────────────────────────────────────────────────────
async function loadSupplierCandidates() {
  const el = document.getElementById('supplier-candidates-list');
  el.innerHTML = '<p class="muted-sm">Φόρτωση…</p>';
  const candidates = await pyCall('get_supplier_merge_candidates') || [];
  if (!candidates.length) { el.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>Δεν βρέθηκαν υποψήφιοι.</p></div>'; return; }
  el.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Κράτηση</th><th>Συγχώνευση</th><th>Βαθμός</th><th>Λόγος</th><th></th></tr></thead>
    <tbody>${candidates.map((c, i) => `
      <tr data-i="${i}">
        <td>${escapeHtml(c.keep_name)}${c.keep_vat ? ` <span class="mono muted-sm">(${escapeHtml(c.keep_vat)})</span>` : ''}</td>
        <td>${escapeHtml(c.merge_name)}${c.merge_vat ? ` <span class="mono muted-sm">(${escapeHtml(c.merge_vat)})</span>` : ''}</td>
        <td><span class="badge badge-${c.tier.toLowerCase()}">${c.tier}</span></td>
        <td class="muted-sm">${escapeHtml(c.reason)}</td>
        <td style="white-space:nowrap;">
          <button class="btn btn-outline btn-sm" data-preview="${i}">Προεπισκόπηση &amp; Συγχώνευση</button>
          <button class="btn btn-outline btn-sm" data-dismiss="${i}">Παράβλεψη</button>
        </td>
      </tr>`).join('')}</tbody></table></div>`;

  el.querySelectorAll('[data-preview]').forEach(btn => btn.addEventListener('click', () => {
    const c = candidates[parseInt(btn.dataset.preview, 10)];
    openMergePreviewModal({
      kind: 'supplier', keep: c.keep_name, merge: c.merge_name,
      keepId: c.keep_id, mergeId: c.merge_id, onDone: loadSupplierCandidates,
    });
  }));
  el.querySelectorAll('[data-dismiss]').forEach(btn => btn.addEventListener('click', async () => {
    const c = candidates[parseInt(btn.dataset.dismiss, 10)];
    await pyCallStrict('dismiss_merge_candidate', { kind: 'supplier', candidate_key: c.dismiss_key });
    loadSupplierCandidates();
  }));
}

function resolveSupplierInput(text) {
  text = (text || '').trim();
  if (!text) return null;
  const suppliers = window.AppState.suppliers || [];
  if (/^\d{9}$/.test(text)) {
    const byVat = suppliers.find(s => s.vat_number === text);
    if (byVat) return byVat;
  }
  const norm = normalizeGreek(text);
  return suppliers.find(s => normalizeGreek(s.name) === norm) || null;
}

attachAutocomplete(document, '#supplier-manual-keep', () => (window.AppState.suppliers || []).map(s => s.name), { normalize: normalizeGreek });
attachAutocomplete(document, '#supplier-manual-merge', () => (window.AppState.suppliers || []).map(s => s.name), { normalize: normalizeGreek });
attachAutocomplete(document, '#supplier-rename-search', () => (window.AppState.suppliers || []).map(s => s.name), { normalize: normalizeGreek });

document.getElementById('supplier-manual-btn').addEventListener('click', () => {
  const keep = resolveSupplierInput(document.getElementById('supplier-manual-keep').value);
  const merge = resolveSupplierInput(document.getElementById('supplier-manual-merge').value);
  if (!keep || !merge) { App.toast('Δεν βρέθηκε προμηθευτής με αυτό το όνομα/ΑΦΜ', 'fail'); return; }
  if (keep.id === merge.id) { App.toast('Ίδιος προμηθευτής και στα δύο πεδία', 'fail'); return; }
  openMergePreviewModal({
    kind: 'supplier', keep: keep.name, merge: merge.name, keepId: keep.id, mergeId: merge.id,
    onDone: loadSupplierCandidates,
  });
});

document.getElementById('supplier-rename-btn').addEventListener('click', async () => {
  const supplier = resolveSupplierInput(document.getElementById('supplier-rename-search').value);
  const newName = document.getElementById('supplier-rename-new').value.trim();
  if (!supplier) { App.toast('Δεν βρέθηκε προμηθευτής με αυτό το όνομα/ΑΦΜ', 'fail'); return; }
  if (!newName) { App.toast('Γράψε το νέο όνομα', 'fail'); return; }
  const btn = document.getElementById('supplier-rename-btn');
  const unlock = _lock(btn);
  try {
    await pyCallStrict('update_supplier', { id: supplier.id, name: newName, vat_number: supplier.vat_number, notes: supplier.notes });
    App.toast('Το όνομα ενημερώθηκε', 'ok');
    document.getElementById('supplier-rename-search').value = '';
    document.getElementById('supplier-rename-new').value = '';
    window.reloadLookups();
    loadSupplierCandidates();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

// ── ΜΗΧΑΝΗΜΑΤΑ ───────────────────────────────────────────────────────────────
async function loadMachineCandidates() {
  const el = document.getElementById('machine-candidates-list');
  el.innerHTML = '<p class="muted-sm">Φόρτωση…</p>';
  const groups = await pyCall('get_machine_merge_candidates') || [];
  const rows = [];
  groups.forEach(g => g.others.forEach(o => rows.push({ keep_id: g.keep_id, keep_name: g.keep_name, id: o.id, name: o.name, dismiss_key: o.dismiss_key })));
  if (!rows.length) { el.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>Δεν βρέθηκαν υποψήφια (αναμενόμενο — το tool πιάνει μόνο διαφορές μορφοποίησης, βλ. σημείωση παραπάνω).</p></div>'; return; }
  el.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>Κράτηση</th><th>Συγχώνευση</th><th></th></tr></thead>
    <tbody>${rows.map((r, i) => `
      <tr data-i="${i}">
        <td>${escapeHtml(r.keep_name)}</td>
        <td>${escapeHtml(r.name)}</td>
        <td style="white-space:nowrap;">
          <button class="btn btn-outline btn-sm" data-preview="${i}">Προεπισκόπηση &amp; Συγχώνευση</button>
          <button class="btn btn-outline btn-sm" data-dismiss="${i}">Παράβλεψη</button>
        </td>
      </tr>`).join('')}</tbody></table></div>`;

  el.querySelectorAll('[data-preview]').forEach(btn => btn.addEventListener('click', () => {
    const r = rows[parseInt(btn.dataset.preview, 10)];
    openMergePreviewModal({
      kind: 'machine', keep: r.keep_name, merge: r.name,
      keepId: r.keep_id, mergeId: r.id, onDone: () => { loadMachineCandidates(); loadOrphanMachines(); },
    });
  }));
  el.querySelectorAll('[data-dismiss]').forEach(btn => btn.addEventListener('click', async () => {
    const r = rows[parseInt(btn.dataset.dismiss, 10)];
    await pyCallStrict('dismiss_merge_candidate', { kind: 'machine', candidate_key: r.dismiss_key });
    loadMachineCandidates();
  }));
}

function resolveMachineInput(text) {
  text = (text || '').trim();
  if (!text) return null;
  const machines = window.AppState.machines || [];
  const norm = normalizeGreek(text);
  return machines.find(m => normalizeGreek(m.name) === norm) || null;
}

attachAutocomplete(document, '#machine-manual-keep', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });
attachAutocomplete(document, '#machine-manual-merge', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });

document.getElementById('machine-manual-btn').addEventListener('click', () => {
  const keep = resolveMachineInput(document.getElementById('machine-manual-keep').value);
  const merge = resolveMachineInput(document.getElementById('machine-manual-merge').value);
  if (!keep || !merge) { App.toast('Δεν βρέθηκε μηχάνημα με αυτό το όνομα', 'fail'); return; }
  if (keep.id === merge.id) { App.toast('Ίδιο μηχάνημα και στα δύο πεδία', 'fail'); return; }
  openMergePreviewModal({
    kind: 'machine', keep: keep.name, merge: merge.name, keepId: keep.id, mergeId: merge.id,
    onDone: () => { loadMachineCandidates(); loadOrphanMachines(); },
  });
});

async function loadOrphanMachines() {
  const el = document.getElementById('orphan-machines-list');
  el.innerHTML = '<p class="muted-sm">Φόρτωση…</p>';
  const orphans = await pyCall('get_orphan_machines') || [];
  if (!orphans.length) { el.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>Κανένα ορφανό μηχάνημα.</p></div>'; return; }
  el.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th style="width:32px;"><input type="checkbox" id="orphan-machine-all" checked></th><th>Μηχάνημα</th><th>Σημείωση</th></tr></thead>
    <tbody>${orphans.map(m => `
      <tr>
        <td><input type="checkbox" class="orphan-machine-cb" value="${m.id}" checked></td>
        <td>${escapeHtml(m.name)}</td>
        <td class="muted-sm">${escapeHtml(m.notes || '—')}</td>
      </tr>`).join('')}</tbody></table></div>
    <div class="form-actions"><button type="button" class="btn btn-danger" id="orphan-machine-delete-btn"></button></div>`;

  const btn = document.getElementById('orphan-machine-delete-btn');
  const boxes = [...el.querySelectorAll('.orphan-machine-cb')];
  const selectedIds = () => boxes.filter(b => b.checked).map(b => parseInt(b.value, 10));
  const refreshBtn = () => {
    const n = selectedIds().length;
    btn.textContent = `Διαγραφή επιλεγμένων (${n})`;
    btn.disabled = n === 0;
  };
  refreshBtn();

  document.getElementById('orphan-machine-all').addEventListener('change', e => {
    boxes.forEach(b => { b.checked = e.target.checked; });
    refreshBtn();
  });
  boxes.forEach(b => b.addEventListener('change', refreshBtn));

  btn.addEventListener('click', async () => {
    const ids = selectedIds();
    if (!(await App.confirmAsync(`Οριστική διαγραφή ${ids.length} ορφανού/ών μηχανήματος/ων;`))) return;
    const unlock = _lock(btn);
    try {
      const result = await pyCallStrict('delete_orphan_machines', { ids });
      const skippedText = result.skipped ? ` (${result.skipped} παραλείφθηκαν — απέκτησαν χρήση εν τω μεταξύ)` : '';
      App.toast(`Διαγράφηκαν ${result.deleted} μηχάνημα/τα${skippedText}`, 'ok');
      window.reloadLookups();
      loadOrphanMachines();
    } catch (e) {
      App.toast(e.message, 'fail');
      unlock();
    }
  });
}

// ── ΠΕΡΙΓΡΑΦΕΣ ───────────────────────────────────────────────────────────────
async function loadDescriptionCandidates() {
  const el = document.getElementById('description-candidates-list');
  el.innerHTML = '<p class="muted-sm">Φόρτωση…</p>';
  const candidates = await pyCall('get_description_merge_candidates') || [];
  if (!candidates.length) { el.innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>Δεν βρέθηκαν υποψήφιες ομαδοποιήσεις.</p></div>'; return; }
  el.innerHTML = candidates.map((c, i) => `
    <div class="card" style="margin-bottom:12px;" data-i="${i}">
      <p style="margin-bottom:8px;"><span class="badge badge-neutral">${escapeHtml(c.category)}</span> Θα γίνουν όλα: <b>${escapeHtml(c.keep)}</b> <span class="muted-sm">(ήδη ${c.keep_count} γραμμές)</span></p>
      <ul style="margin:0 0 12px 20px; font-size:12.5px; color:var(--muted);">
        ${c.variants.map(v => `<li>${escapeHtml(v.description)} <span class="muted-sm">(${v.count} γραμμές)</span></li>`).join('')}
      </ul>
      <div class="form-actions" style="margin-top:0;">
        <button class="btn btn-outline btn-sm" data-merge="${i}">Συγχώνευση όλων (${c.affected_rows} γραμμές)</button>
        <button class="btn btn-outline btn-sm" data-dismiss="${i}">Παράβλεψη όλων</button>
      </div>
    </div>
  `).join('');

  el.querySelectorAll('[data-merge]').forEach(btn => btn.addEventListener('click', async () => {
    const c = candidates[parseInt(btn.dataset.merge, 10)];
    const unlock = _lock(btn);
    try {
      await pyCallStrict('merge_item_descriptions', { category: c.category, keep: c.keep, merge_list: c.variants.map(v => v.description) });
      App.toast('Η ομαδοποίηση ολοκληρώθηκε', 'ok');
      loadDescriptionCandidates();
    } catch (e) {
      App.toast(e.message, 'fail');
      unlock();
    }
  }));
  el.querySelectorAll('[data-dismiss]').forEach(btn => btn.addEventListener('click', async () => {
    const c = candidates[parseInt(btn.dataset.dismiss, 10)];
    for (const v of c.variants) {
      await pyCallStrict('dismiss_merge_candidate', { kind: 'description', candidate_key: v.dismiss_key });
    }
    loadDescriptionCandidates();
  }));
}

loadSupplierCandidates();
loaded.suppliers = true;
