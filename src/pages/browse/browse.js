import {
  escapeHtml, fmtDate, fmtQty, _lock, todayInput,
  normalizeGreek, normalizeCategory, normalizeMachineCode, attachAutocomplete,
} from '../../../js/utils.js';

// ── ΣΤΑΘΕΡΕΣ ΣΟΒΑΡΟΤΗΤΑΣ ─────────────────────────────────────────────────────
const SEV_LABEL = { severe: 'Σοβαρό', moderate: 'Μέτριο', duplicate: 'Διπλότυπο', reviewed: 'Επιθεωρήθηκε' };
const SEV_BADGE_CLASS = { severe: 'rejected', duplicate: 'rejected', moderate: 'pending', reviewed: 'confirmed' };
const SEV_ACTIVE = { severe: true, duplicate: true, moderate: true };

function normalizeForSearch(s) {
  return normalizeGreek(s).replace(/[-/\s]+/g, '');
}

function canonicalMachineName(name) {
  if (!name) return name;
  const machines = window.AppState.machines || [];
  if (machines.some(m => m.name === name)) return name;
  const norm = normalizeMachineCode(name);
  if (!norm) return name;
  const match = machines.find(m => normalizeMachineCode(m.name) === norm);
  return match ? match.name : name;
}

// ── ΠΡΟΕΙΔΟΠΟΙΗΣΗ ΠΙΝΑΚΙΔΑΣ ───────────────────────────────────────────────────
// Μορφή ελληνικής πινακίδας (3 από τα 14 κοινά γράμματα + 4 ψηφία) — ίδιος κανόνας
// με backend's _is_plate_code/intake-tool's PLATE_RE. ΝΕΟ μηχάνημα με τέτοια μορφή
// είναι συνήθως το φορτηγό παράδοσης του προμηθευτή, όχι δικό μας μηχάνημα.
const PLATE_RE = /^[ABEZHIKMNOPTYX]{3}\d{4}$/;
const PLATE_WARN_TEXT = 'Νέο μηχάνημα με μορφή πινακίδας — έλεγξε στο PDF ότι δεν είναι το όχημα ' +
  'παράδοσης του προμηθευτή (πεδίο «ΑΡ. ΟΧΗΜΑΤΟΣ»/«ΜΕΤΑΦΟΡΙΚΟ ΜΕΣΟ»)';

function isUnknownPlate(name) {
  const norm = normalizeMachineCode(name);
  return PLATE_RE.test(norm) && !(window.AppState.machines || []).some(m => normalizeMachineCode(m.name) === norm);
}

function markPlateWarning(input) {
  const warn = isUnknownPlate(input.value);
  input.classList.toggle('plate-warn', warn);
  input.title = warn ? PLATE_WARN_TEXT : '';
}

function wirePlateWarnings(containerEl, selector) {
  const handler = (e) => { const el = e.target.closest(selector); if (el) markPlateWarning(el); };
  containerEl.addEventListener('input', handler);
  containerEl.addEventListener('change', handler);
}

// ── ΠΡΟΕΙΔΟΠΟΙΗΣΗ ΠΑΡΟΜΟΙΟΥ ΠΡΟΜΗΘΕΥΤΗ ────────────────────────────────────────
const SUPPLIER_NAME_STOPWORDS = new Set([
  'αφοι', 'αφων', 'σια', 'υιοι', 'υιος', 'υιου', 'υιων',
  'ανωνυμη', 'εταιρια', 'εταιρειας', 'ομορρυθμη', 'ετερορρυθμη',
  'ιδιωτικη', 'κεφαλαιουχικη', 'περιορισμενης', 'ευθυνης', 'ike',
]);

function nameTokens(s) {
  return new Set(
    normalizeGreek(s).split(/[^a-zα-ω0-9]+/)
      .filter(w => w.length >= 3 && !SUPPLIER_NAME_STOPWORDS.has(w))
  );
}

function normalizeVat(v) {
  if (!v) return null;
  v = String(v).trim().toUpperCase().replace(/[\s\-]/g, '');
  if (v.startsWith('EL')) v = v.slice(2);
  return v || null;
}

function hammingCloseVat(a, b) {
  if (!a || !b || a.length !== b.length || a.length < 8) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
  return diff > 0 && diff <= 2;
}

// Επιστρέφει null αν δεν υπάρχει κίνδυνος διπλότυπου (ταιριάζει ακριβώς ή δεν
// μοιάζει με τίποτα), αλλιώς τον πιο κοντινό υπάρχοντα προμηθευτή.
function findSimilarSupplier(name, vat) {
  const suppliers = window.AppState.suppliers || [];
  const normName = normalizeGreek(name);
  const normVat = normalizeVat(vat);
  if (!normName && !normVat) return null;
  const fnTokens = nameTokens(name);

  for (const s of suppliers) {
    const sVat = normalizeVat(s.vat_number);
    if ((normName && normalizeGreek(s.name) === normName) || (normVat && sVat && normVat === sVat)) {
      return null;
    }
  }
  let best = null;
  for (const s of suppliers) {
    const sVat = normalizeVat(s.vat_number);
    const vatClose = hammingCloseVat(normVat, sVat);
    const sTokens = nameTokens(s.name);
    const overlap = [...fnTokens].filter(t => sTokens.has(t)).length;
    const minSize = Math.min(fnTokens.size, sTokens.size);
    const nameClose = overlap >= 2 || (overlap === 1 && minSize <= 1);
    if (vatClose || nameClose) { best = s; break; }
  }
  return best;
}

let browseRows = [];
let browseSeverityById = {};
let browseReasonById = {};
let browseSeverityFilter = '';
let browseCategoryFilter = '';
const BROWSE_PAGE_SIZE = 200;
let browsePage = 0;

async function loadBrowse() {
  const category = browseCategoryFilter || null;
  const [rows, flagged, summary] = await Promise.all([
    pyCall('list_invoice_items_by_category', { category }),
    pyCall('get_flagged_invoices'),
    pyCall('get_invoice_status_summary'),
  ]);
  browseRows = rows || [];
  browseSeverityById = Object.fromEntries((flagged || []).map(f => [f.invoice_id, f.severity]));
  browseReasonById = Object.fromEntries((flagged || []).map(f => [f.invoice_id, f.reason]));
  renderStatusStats(summary);
  browsePage = 0;
  applyBrowseSearch(browseRows);
}

function renderStatusStats(summary) {
  if (!summary) return;
  const sevCards = [
    { key: '', label: 'Σύνολο Τιμολογίων', val: summary.total_invoices, sev: '' },
    { key: 'duplicate', label: 'Διπλότυπα', val: summary.flagged_duplicate, sev: summary.flagged_duplicate ? 'sev-danger' : '' },
    { key: 'severe', label: 'Σοβαρές Ελλείψεις', val: summary.flagged_severe, sev: summary.flagged_severe ? 'sev-danger' : '' },
    { key: 'moderate', label: 'Μέτριες Ελλείψεις', val: summary.flagged_moderate, sev: summary.flagged_moderate ? 'sev-warning' : '' },
    { key: 'reviewed', label: 'Επιθεωρημένα', val: summary.flagged_reviewed, sev: '' },
  ];
  const sevGrid = document.getElementById('status-stats-grid');
  sevGrid.innerHTML = sevCards.map(c => `
    <div class="stat-card stat-clickable ${c.sev} ${c.key === browseSeverityFilter ? 'stat-active' : ''}" data-sev-filter="${c.key}">
      <div class="stat-val">${c.val}</div>
      <div class="stat-label">${c.label}</div>
    </div>
  `).join('');
  sevGrid.querySelectorAll('[data-sev-filter]').forEach(el => el.addEventListener('click', () => {
    const f = el.dataset.sevFilter;
    browseSeverityFilter = (browseSeverityFilter === f) ? '' : f;
    browsePage = 0;
    if (browseSeverityFilter && browseCategoryFilter) {
      browseCategoryFilter = '';
      loadBrowse();
      return;
    }
    renderStatusStats(summary);
    applyBrowseSearch(browseRows);
  }));

  const catGrid = document.getElementById('status-category-grid');
  catGrid.innerHTML = (summary.by_category || []).map(c => `
    <div class="stat-card stat-clickable ${c.category === browseCategoryFilter ? 'stat-active' : ''}" data-cat-filter="${escapeHtml(c.category)}">
      <div class="stat-val">${c.count}</div>
      <div class="stat-label">${escapeHtml(c.category)}</div>
    </div>
  `).join('');
  catGrid.querySelectorAll('[data-cat-filter]').forEach(el => el.addEventListener('click', () => {
    browseCategoryFilter = (browseCategoryFilter === el.dataset.catFilter) ? '' : el.dataset.catFilter;
    loadBrowse();
  }));
}

function applyBrowseSearch(rows) {
  const body = document.getElementById('browse-body');
  const note = document.getElementById('browse-result-note');
  const pagination = document.getElementById('browse-pagination');
  const qTerms = document.getElementById('browse-search').value
    .split(/[,;]+/)
    .map(t => normalizeForSearch(t))
    .filter(Boolean);
  const dateFrom = document.getElementById('browse-date-from').value || null;
  const dateTo = document.getElementById('browse-date-to').value || null;

  let filtered = browseSeverityFilter ? rows.filter(r => browseSeverityById[r.invoice_id] === browseSeverityFilter) : rows;
  filtered = qTerms.length ? filtered.filter(r => {
    const haystack = normalizeForSearch(`${r.supplier_name || ''} ${r.supplier_vat || ''} ${r.doc_number || ''} ${r.doc_date || ''} ${r.machine_name || ''} ${r.description || ''} ${r.category || ''} ${r.notes || ''}`);
    return qTerms.every(t => haystack.includes(t));
  }) : filtered;
  if (dateFrom) filtered = filtered.filter(r => r.doc_date && r.doc_date >= dateFrom);
  if (dateTo) filtered = filtered.filter(r => r.doc_date && r.doc_date <= dateTo);

  if (!filtered.length) {
    note.textContent = '';
    pagination.innerHTML = '';
    body.innerHTML = `<tr><td colspan="10"><div class="empty-state"><div class="icon">🔎</div><p>Καμία αντιστοιχία.</p></div></td></tr>`;
    return;
  }

  filtered = filtered.slice().sort((a, b) => {
    const sa = SEV_ACTIVE[browseSeverityById[a.invoice_id]], sb = SEV_ACTIVE[browseSeverityById[b.invoice_id]];
    if (!!sa === !!sb) return 0;
    return sa ? -1 : 1;
  });

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / BROWSE_PAGE_SIZE));
  if (browsePage >= totalPages) browsePage = totalPages - 1;
  if (browsePage < 0) browsePage = 0;

  if (totalPages > 1) {
    const from = browsePage * BROWSE_PAGE_SIZE + 1;
    const to = Math.min(total, from + BROWSE_PAGE_SIZE - 1);
    filtered = filtered.slice(browsePage * BROWSE_PAGE_SIZE, browsePage * BROWSE_PAGE_SIZE + BROWSE_PAGE_SIZE);
    note.textContent = `${from}–${to} από ${total} αποτελέσματα`;
    pagination.innerHTML = `
      <button class="btn btn-outline btn-sm" id="browse-page-prev" ${browsePage === 0 ? 'disabled' : ''}>← Προηγούμενη</button>
      <span class="muted-sm">Σελίδα ${browsePage + 1} από ${totalPages}</span>
      <button class="btn btn-outline btn-sm" id="browse-page-next" ${browsePage >= totalPages - 1 ? 'disabled' : ''}>Επόμενη →</button>
    `;
    document.getElementById('browse-page-prev').addEventListener('click', () => {
      browsePage--;
      applyBrowseSearch(browseRows);
    });
    document.getElementById('browse-page-next').addEventListener('click', () => {
      browsePage++;
      applyBrowseSearch(browseRows);
    });
  } else {
    note.textContent = qTerms.length || browseSeverityFilter || dateFrom || dateTo ? `${total} αποτελέσματα` : '';
    pagination.innerHTML = '';
  }

  body.innerHTML = filtered.map(r => {
    const sev = browseSeverityById[r.invoice_id];
    return `
    <tr class="${sev ? `sev-${sev}` : ''}">
      <td class="mono">${escapeHtml(r.doc_date ? fmtDate(r.doc_date) : '—')}</td>
      <td class="mono" title="${escapeHtml(r.supplier_name || '')}">${escapeHtml(r.supplier_vat || r.supplier_name || '—')}</td>
      <td class="mono">${escapeHtml(r.doc_number || '—')}</td>
      <td>${escapeHtml(r.category || '—')}</td>
      <td>${escapeHtml(r.description || '—')}</td>
      <td class="mono text-right" style="white-space:nowrap;">${r.quantity != null ? fmtQty(r.quantity) : '—'} ${escapeHtml(r.unit || '')}</td>
      <td>${escapeHtml(r.machine_name || '—')}</td>
      <td>${r.efk_eligible ? '✓' : '—'}</td>
      <td><span class="control-cell">${sev ? `
        <span class="badge badge-${SEV_BADGE_CLASS[sev]}" title="${escapeHtml(browseReasonById[r.invoice_id] || '')}">${SEV_LABEL[sev]}</span>
        ${sev === 'reviewed'
          ? `<button class="btn btn-outline btn-sm" data-unreview-invoice="${r.invoice_id}" title="Αναίρεση επιθεώρησης">↺</button>`
          : `<button class="btn btn-outline btn-sm" data-review-invoice="${r.invoice_id}" title="Το είδα, το αφήνω όπως είναι">👁</button>`}
      ` : '—'}</span></td>
      <td><span class="row-actions">
        ${r.pdf_available ? `<button class="btn btn-outline btn-sm" data-open-pdf="${escapeHtml(r.source_pdf_filename)}" title="Άνοιγμα PDF">📄</button>` : ''}
        <button class="btn btn-outline btn-sm" data-edit-invoice="${r.invoice_id}" title="Δες/διόρθωσε το τιμολόγιο">✏️</button>
      </span></td>
    </tr>
  `;
  }).join('');

  body.querySelectorAll('[data-open-pdf]').forEach(btn => btn.addEventListener('click', async () => {
    const res = await window.api.openStoredFile(btn.dataset.openPdf);
    if (!res.ok) App.toast('Δεν ήταν δυνατό το άνοιγμα: ' + res.error, 'fail');
  }));
  body.querySelectorAll('[data-edit-invoice]').forEach(btn => btn.addEventListener('click', () => {
    openEditInvoice(parseInt(btn.dataset.editInvoice, 10));
  }));
  body.querySelectorAll('[data-review-invoice]').forEach(btn => btn.addEventListener('click', () => {
    document.getElementById('review-invoice-id').value = btn.dataset.reviewInvoice;
    document.getElementById('review-note').value = '';
    document.getElementById('review-invoice-modal').classList.add('open');
  }));
  body.querySelectorAll('[data-unreview-invoice]').forEach(btn => btn.addEventListener('click', () => {
    App.confirmDelete('Αναίρεση επιθεώρησης — το τιμολόγιο θα ξαναϋπολογιστεί αυτόματα ως σοβαρό/μέτριο;', async () => {
      try {
        await pyCallStrict('unreview_flagged_invoice', { invoice_id: parseInt(btn.dataset.unreviewInvoice, 10) });
        loadBrowse();
      } catch (e) {
        App.toast(e.message, 'fail');
      }
    });
  }));
}

document.getElementById('review-cancel-btn').addEventListener('click', () => {
  document.getElementById('review-invoice-modal').classList.remove('open');
});
document.getElementById('review-ok-btn').addEventListener('click', async () => {
  const invoiceId = parseInt(document.getElementById('review-invoice-id').value, 10);
  const note = document.getElementById('review-note').value || null;
  document.getElementById('review-invoice-modal').classList.remove('open');
  try {
    await pyCallStrict('review_flagged_invoice', { invoice_id: invoiceId, note });
    App.toast('✅ Επιθεωρήθηκε', 'ok');
    loadBrowse();
  } catch (e) {
    App.toast(e.message, 'fail');
  }
});

let browseSearchDebounce = null;
document.getElementById('browse-search').addEventListener('input', () => {
  clearTimeout(browseSearchDebounce);
  browseSearchDebounce = setTimeout(() => {
    browsePage = 0;
    applyBrowseSearch(browseRows);
  }, 200);
});
['browse-date-from', 'browse-date-to'].forEach(id => {
  document.getElementById(id).addEventListener('change', () => {
    browsePage = 0;
    applyBrowseSearch(browseRows);
  });
});

// ── ΔΙΟΡΘΩΣΗ ΤΙΜΟΛΟΓΙΟΥ ──────────────────────────────────────────────────────
// Κρατάει το τρέχον συνδεδεμένο PDF ώστε το "Αποθήκευση" να το ξαναστείλει —
// αλλιώς το backend το διαβάζει σαν κενό και σβήνει τη σύνδεση από τη βάση σε
// κάθε αποθήκευση (ίδιο bug με το intake-tool, 2026-08-23).
let currentPdfFilename = null;
// Απόλυτη διαδρομή PDF επιλεγμένου σε ΝΕΟ τιμολόγιο (δεν υπάρχει ακόμα invoice_id
// για attach_pdf) — μένει σε αναμονή, επισυνάπτεται μετά το add_invoice_from_data
// (ίδιο μοτίβο με το παλιό, πλέον καταργημένο «Τιμολόγια» tab).
let pendingNewPdfPath = null;

function refreshEditPdfStatus(r) {
  const status = document.getElementById('edit-pdf-status');
  const openBtn = document.getElementById('edit-pdf-open-btn');
  currentPdfFilename = r.pdf_available ? r.source_pdf_filename : null;
  if (r.pdf_available) {
    status.textContent = r.source_pdf_filename;
    openBtn.style.display = '';
    openBtn.dataset.openPdf = r.source_pdf_filename;
  } else {
    status.textContent = 'Δεν υπάρχει συνδεδεμένο PDF';
    openBtn.style.display = 'none';
    delete openBtn.dataset.openPdf;
  }
}

function refreshEditSupplierWarning() {
  const nameInput = document.getElementById('edit-supplier-name');
  const vatInput = document.getElementById('edit-supplier-vat');
  const warn = document.getElementById('edit-supplier-warning');
  const similar = findSimilarSupplier(nameInput.value, vatInput.value);
  if (similar) {
    warn.style.display = '';
    warn.innerHTML = `⚠ Παρόμοιος υπάρχων προμηθευτής: <b>${escapeHtml(similar.name)}</b>` +
      (similar.vat_number ? ` (ΑΦΜ ${escapeHtml(similar.vat_number)})` : '') +
      ` — <button type="button" class="btn btn-outline btn-sm" data-use-supplier>Χρήση αυτού</button>`;
    warn.querySelector('[data-use-supplier]').addEventListener('click', () => {
      nameInput.value = similar.name;
      vatInput.value = similar.vat_number || '';
      refreshEditSupplierWarning();
    });
  } else {
    warn.style.display = 'none';
    warn.innerHTML = '';
  }
}
document.getElementById('edit-supplier-name').addEventListener('input', refreshEditSupplierWarning);
document.getElementById('edit-supplier-vat').addEventListener('input', refreshEditSupplierWarning);

// Μία γραμμή <tr> του πίνακα — item={} για ολοκαίνουρια γραμμή (χωρίς id,
// εισάγεται στο update_invoice_from_data ως νέα, βλ. database.py).
function editItemRowHtml(it) {
  const machineName = it.machine_id ? ((window.AppState.machines || []).find(m => m.id === it.machine_id) || {}).name || '' : '';
  const splitBtn = it.id ? `<span class="items-remove-btn" data-split-row-btn title="Διάσπαση σε πολλά μηχανήματα" style="color:var(--navy3); margin-right:8px;">⑃</span>` : '';
  return `
    <tr data-item-row data-item-id="${it.id ?? ''}">
      <td><input type="text" data-f="description" value="${escapeHtml(it.description || '')}"></td>
      <td><input type="text" data-f="category" value="${escapeHtml(it.category || '')}"></td>
      <td><input type="number" step="0.001" data-f="quantity" value="${it.quantity ?? ''}" style="width:80px;"></td>
      <td><input type="text" data-f="unit" value="${escapeHtml(it.unit || '')}" style="width:56px;"></td>
      <td><input type="number" step="0.001" data-f="unit_price" value="${it.unit_price ?? ''}" style="width:90px;"></td>
      <td><input type="number" step="0.01" data-f="value" value="${it.value ?? ''}" style="width:90px;"></td>
      <td><input type="number" step="0.1" data-f="vat_pct" value="${it.vat_pct ?? ''}" style="width:64px;"></td>
      <td><input type="text" data-f="machine_name" value="${escapeHtml(machineName)}"></td>
      <td style="text-align:center;"><input type="checkbox" data-f="efk_eligible" ${it.efk_eligible ? 'checked' : ''} style="width:auto;"></td>
      <td>${splitBtn}<span class="items-remove-btn" data-remove-row title="Διαγραφή γραμμής">✕</span></td>
    </tr>
  `;
}

function renderEditItemsTable(items) {
  document.getElementById('edit-items-body').innerHTML = items.map(editItemRowHtml).join('');
  document.querySelectorAll('#edit-items-body [data-f="machine_name"]').forEach(markPlateWarning);
}

wirePlateWarnings(document.getElementById('edit-items-body'), '[data-f="machine_name"]');
attachAutocomplete(document.getElementById('edit-items-body'), '[data-f="machine_name"]', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });

// Event delegation στο tbody (μία φορά, στο module-load) — αν ξαναγραφόταν σε
// κάθε render/προσθήκη γραμμής θα κολλούσαν διπλά listeners στις ήδη υπάρχουσες.
document.getElementById('edit-items-body').addEventListener('click', (e) => {
  const splitBtn = e.target.closest('[data-split-row-btn]');
  if (splitBtn) {
    openSplitModal(splitBtn.closest('tr'));
    return;
  }
  const btn = e.target.closest('[data-remove-row]');
  if (!btn) return;
  const tr = btn.closest('tr');
  const itemId = tr.dataset.itemId;
  if (!itemId) { tr.remove(); return; } // ολοκαίνουρια γραμμή, ποτέ αποθηκευμένη — απλή αφαίρεση
  App.confirmDelete('Διαγραφή αυτής της γραμμής από το τιμολόγιο; Δεν αναιρείται.', async () => {
    try {
      await pyCallStrict('delete_invoice_item', { item_id: parseInt(itemId, 10) });
      tr.remove();
      App.toast('Η γραμμή διαγράφηκε', 'ok');
    } catch (err) {
      App.toast(err.message, 'fail');
    }
  });
});

// ── Διάσπαση γραμμής σε πολλά μηχανήματα ──────────────────────────────────────
attachAutocomplete(document.getElementById('split-rows'), '.split-machine', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });

function splitRowHtml(machineName, quantity, value) {
  return `
    <div data-split-row style="display:flex; gap:8px; align-items:center; margin-bottom:6px;">
      <input type="text" class="split-machine" placeholder="Μηχάνημα" value="${escapeHtml(machineName || '')}" style="flex:2;">
      <input type="number" step="0.001" class="split-qty" placeholder="Ποσότητα" value="${quantity ?? ''}" style="width:100px;">
      <input type="number" step="0.01" class="split-value" placeholder="Αξία" value="${value ?? ''}" style="width:100px;">
      <span class="items-remove-btn" data-split-remove title="Αφαίρεση">✕</span>
    </div>`;
}

function recomputeSplitSums() {
  const rows = Array.from(document.querySelectorAll('#split-rows [data-split-row]'));
  const qty = rows.reduce((s, r) => s + (parseFloat(r.querySelector('.split-qty').value) || 0), 0);
  const val = rows.reduce((s, r) => s + (parseFloat(r.querySelector('.split-value').value) || 0), 0);
  document.getElementById('split-sum-qty').textContent = qty;
  document.getElementById('split-sum-val').textContent = val.toFixed(2);
  const origQty = parseFloat(document.getElementById('split-item-orig-qty').textContent) || 0;
  const origVal = parseFloat(document.getElementById('split-item-orig-val').textContent) || 0;
  const matches = rows.length >= 2 && Math.abs(qty - origQty) < 0.001 && Math.abs(val - origVal) < 0.01;
  document.getElementById('split-sum-mismatch').style.display = matches ? 'none' : '';
  document.getElementById('split-item-ok-btn').disabled = !matches;
}

document.getElementById('split-rows').addEventListener('input', recomputeSplitSums);
document.getElementById('split-rows').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-split-remove]');
  if (!btn) return;
  btn.closest('[data-split-row]').remove();
  recomputeSplitSums();
});

document.getElementById('split-add-row-btn').addEventListener('click', () => {
  document.getElementById('split-rows').insertAdjacentHTML('beforeend', splitRowHtml('', '', ''));
  recomputeSplitSums();
});

function openSplitModal(tr) {
  const itemId = tr.dataset.itemId;
  const description = tr.querySelector('[data-f="description"]').value;
  const quantity = parseFloat(tr.querySelector('[data-f="quantity"]').value) || 0;
  const value = parseFloat(tr.querySelector('[data-f="value"]').value) || 0;
  const machineName = tr.querySelector('[data-f="machine_name"]').value;

  document.getElementById('split-item-id').value = itemId;
  document.getElementById('split-item-desc').textContent = description;
  document.getElementById('split-item-orig-qty').textContent = quantity;
  document.getElementById('split-item-orig-val').textContent = value.toFixed(2);

  const half = Math.round((quantity / 2) * 1000) / 1000;
  const halfVal = Math.round((value / 2) * 100) / 100;
  document.getElementById('split-rows').innerHTML =
    splitRowHtml(machineName, half, halfVal) +
    splitRowHtml('', quantity - half, value - halfVal);
  recomputeSplitSums();
  document.getElementById('split-item-modal').classList.add('open');
}

document.getElementById('split-item-cancel-btn').addEventListener('click', () => {
  document.getElementById('split-item-modal').classList.remove('open');
});

document.getElementById('split-item-ok-btn').addEventListener('click', async () => {
  const itemId = parseInt(document.getElementById('split-item-id').value, 10);
  const rows = Array.from(document.querySelectorAll('#split-rows [data-split-row]'));
  const splits = rows.map(r => ({
    machine_name: r.querySelector('.split-machine').value.trim() || null,
    quantity: parseFloat(r.querySelector('.split-qty').value),
    value: parseFloat(r.querySelector('.split-value').value),
  }));
  const unlock = _lock(document.getElementById('split-item-ok-btn'));
  try {
    await pyCallStrict('split_invoice_item', { item_id: itemId, splits });
    document.getElementById('split-item-modal').classList.remove('open');
    App.toast('Η γραμμή διασπάστηκε', 'ok');
    const invoiceId = parseInt(document.getElementById('edit-invoice-id').value, 10);
    await openEditInvoice(invoiceId);
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

document.getElementById('edit-add-item-btn').addEventListener('click', () => {
  document.getElementById('edit-items-body').insertAdjacentHTML('beforeend', editItemRowHtml({}));
});

async function openEditInvoice(invoiceId) {
  const inv = await pyCall('get_invoice', { id: invoiceId });
  if (!inv) { App.toast('Δεν ήταν δυνατή η φόρτωση του τιμολογίου', 'fail'); return; }
  const supplier = (window.AppState.suppliers || []).find(s => s.id === inv.supplier_id);
  pendingNewPdfPath = null;
  refreshEditPdfStatus(inv);
  document.getElementById('edit-invoice-modal-title').textContent = `Διόρθωση Τιμολογίου #${inv.id}`;
  document.getElementById('edit-invoice-delete-btn').style.display = '';
  document.getElementById('edit-invoice-id').value = inv.id;
  document.getElementById('edit-supplier-name').value = supplier ? supplier.name : '';
  document.getElementById('edit-supplier-vat').value = supplier ? (supplier.vat_number || '') : '';
  document.getElementById('edit-doc-type').value = inv.doc_type || '';
  document.getElementById('edit-doc-number').value = inv.doc_number || '';
  document.getElementById('edit-doc-date').value = inv.doc_date || '';
  document.getElementById('edit-doc-time').value = inv.doc_time || '';
  document.getElementById('edit-customer-name').value = inv.customer_name || '';
  document.getElementById('edit-customer-vat').value = inv.customer_vat || '';
  document.getElementById('edit-customer-doy').value = inv.customer_doy || '';
  document.getElementById('edit-customer-address').value = inv.customer_address || '';
  document.getElementById('edit-customer-phone').value = inv.customer_phone || '';
  document.getElementById('edit-payment-method').value = inv.payment_method || '';
  document.getElementById('edit-notes').value = inv.notes || '';
  document.getElementById('edit-net-amount').value = inv.net_amount ?? '';
  document.getElementById('edit-vat-amount').value = inv.vat_amount ?? '';
  document.getElementById('edit-total-amount').value = inv.total_amount ?? '';
  renderEditItemsTable(inv.items || []);
  refreshEditSupplierWarning();
  document.getElementById('edit-invoice-modal').classList.add('open');
}

// Ίδιο modal με το openEditInvoice, αλλά χωρίς invoice_id -- η αποθήκευση πάει σε
// add_invoice_from_data αντί για update_invoice_from_data (βλ. edit-invoice-save-btn).
// Καλύπτει ό,τι έκανε το παλιό, πλέον καταργημένο tab «Τιμολόγια» (βλ. TODO/DONE),
// απλώς σπάνια χρειάζεται -- η πλειονότητα των τιμολογίων μπαίνει μέσω Εισαγωγή.
function openNewInvoice() {
  pendingNewPdfPath = null;
  currentPdfFilename = null;
  document.getElementById('edit-invoice-modal-title').textContent = 'Νέο Τιμολόγιο';
  document.getElementById('edit-invoice-delete-btn').style.display = 'none';
  document.getElementById('edit-invoice-id').value = '';
  document.getElementById('edit-supplier-name').value = '';
  document.getElementById('edit-supplier-vat').value = '';
  document.getElementById('edit-doc-type').value = '';
  document.getElementById('edit-doc-number').value = '';
  document.getElementById('edit-doc-date').value = todayInput();
  document.getElementById('edit-doc-time').value = '';
  document.getElementById('edit-customer-name').value = '';
  document.getElementById('edit-customer-vat').value = '';
  document.getElementById('edit-customer-doy').value = '';
  document.getElementById('edit-customer-address').value = '';
  document.getElementById('edit-customer-phone').value = '';
  document.getElementById('edit-payment-method').value = '';
  document.getElementById('edit-notes').value = '';
  document.getElementById('edit-net-amount').value = '';
  document.getElementById('edit-vat-amount').value = '';
  document.getElementById('edit-total-amount').value = '';
  document.getElementById('edit-pdf-status').textContent = 'Κανένα αρχείο';
  document.getElementById('edit-pdf-open-btn').style.display = 'none';
  renderEditItemsTable([]);
  refreshEditSupplierWarning();
  document.getElementById('edit-invoice-modal').classList.add('open');
}
document.getElementById('new-invoice-btn').addEventListener('click', openNewInvoice);

function closeEditModal() {
  document.getElementById('edit-invoice-modal').classList.remove('open');
}
document.getElementById('edit-invoice-cancel-btn').addEventListener('click', closeEditModal);

document.getElementById('edit-pdf-open-btn').addEventListener('click', async () => {
  const filename = document.getElementById('edit-pdf-open-btn').dataset.openPdf;
  if (!filename) return;
  const res = await window.api.openStoredFile(filename);
  if (!res.ok) App.toast('Δεν ήταν δυνατό το άνοιγμα: ' + res.error, 'fail');
});

// Χειροκίνητη επισύναψη — δικλείδα ασφαλείας για όποτε το αυτόματο attach κατά
// το confirm δεν έτρεξε. `attach_pdf` εδώ (invoicebook's ήδη υπάρχον cmd, ίδιο
// με τη σελίδα «Τιμολόγια») θέλει `{id, source_path}` και επιστρέφει
// `source_pdf_filename` — ΔΙΑΦΟΡΕΤΙΚΟ payload/response σχήμα από το intake-tool.
document.getElementById('edit-pdf-attach-btn').addEventListener('click', async () => {
  const filePath = await window.api.pickPdfFile();
  if (!filePath) return;
  if (!document.getElementById('edit-invoice-id').value) {
    // Νέο τιμολόγιο -- δεν υπάρχει ακόμα id για attach_pdf, αναβολή μέχρι το save
    // (ίδιο μοτίβο με το παλιό, πλέον καταργημένο «Τιμολόγια» tab).
    pendingNewPdfPath = filePath;
    document.getElementById('edit-pdf-status').textContent = filePath.split(/[\\/]/).pop() + ' (θα επισυναφθεί μετά την αποθήκευση)';
    document.getElementById('edit-pdf-open-btn').style.display = 'none';
    return;
  }
  if (currentPdfFilename && !(await App.confirmAsync(
    `Το τιμολόγιο έχει ήδη PDF («${currentPdfFilename}»). Αντικατάσταση; Το παλιό αρχείο θα σβηστεί.`
  ))) return;
  const invoiceId = parseInt(document.getElementById('edit-invoice-id').value, 10);
  const unlock = _lock(document.getElementById('edit-pdf-attach-btn'));
  try {
    const res = await pyCallStrict('attach_pdf', { id: invoiceId, source_path: filePath });
    App.toast('Το PDF επισυνάφθηκε', 'ok');
    await loadBrowse();
    currentPdfFilename = res.source_pdf_filename;
    const inv = await pyCall('get_invoice', { id: invoiceId });
    if (inv) refreshEditPdfStatus(inv);
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

// Αποθήκευση μέσω update_invoice_from_data (υπάρχον τιμολόγιο) ή
// add_invoice_from_data (νέο, edit-invoice-id κενό -- βλ. openNewInvoice).
document.getElementById('edit-invoice-save-btn').addEventListener('click', async () => {
  const invoiceIdVal = document.getElementById('edit-invoice-id').value;
  const isNew = !invoiceIdVal;
  const numOrNull = (v) => (v === '' ? null : parseFloat(v));
  const itemRows = Array.from(document.getElementById('edit-items-body').querySelectorAll('tr[data-item-row]'));
  const items = itemRows.map(tr => {
    const val = (f) => tr.querySelector(`[data-f="${f}"]`).value;
    const item = {
      description: val('description') || null,
      category: normalizeCategory(val('category')) || null,
      quantity: numOrNull(val('quantity')),
      unit: val('unit') || null,
      unit_price: numOrNull(val('unit_price')),
      value: numOrNull(val('value')),
      vat_pct: numOrNull(val('vat_pct')),
      machine_name: canonicalMachineName(val('machine_name')) || null,
      efk_eligible: tr.querySelector('[data-f="efk_eligible"]').checked,
    };
    if (tr.dataset.itemId) item.id = parseInt(tr.dataset.itemId, 10);
    return item;
  });
  const data = {
    supplier_name: document.getElementById('edit-supplier-name').value || null,
    supplier_vat: document.getElementById('edit-supplier-vat').value || null,
    doc_type: document.getElementById('edit-doc-type').value || null,
    doc_number: document.getElementById('edit-doc-number').value || null,
    doc_date: document.getElementById('edit-doc-date').value || null,
    doc_time: document.getElementById('edit-doc-time').value || null,
    customer_name: document.getElementById('edit-customer-name').value || null,
    customer_vat: document.getElementById('edit-customer-vat').value || null,
    customer_doy: document.getElementById('edit-customer-doy').value || null,
    customer_address: document.getElementById('edit-customer-address').value || null,
    customer_phone: document.getElementById('edit-customer-phone').value || null,
    payment_method: document.getElementById('edit-payment-method').value || null,
    notes: document.getElementById('edit-notes').value || null,
    net_amount: numOrNull(document.getElementById('edit-net-amount').value),
    vat_amount: numOrNull(document.getElementById('edit-vat-amount').value),
    total_amount: numOrNull(document.getElementById('edit-total-amount').value),
    source_pdf_filename: currentPdfFilename,
    items,
  };
  const unlock = _lock(document.getElementById('edit-invoice-save-btn'));
  try {
    let savedId;
    if (isNew) {
      const res = await pyCallStrict('add_invoice_from_data', { data });
      savedId = res.id;
      App.toast('Το τιμολόγιο προστέθηκε', 'ok');
    } else {
      savedId = parseInt(invoiceIdVal, 10);
      await pyCallStrict('update_invoice_from_data', { id: savedId, data });
      App.toast('Η εγγραφή ενημερώθηκε', 'ok');
    }
    if (isNew && pendingNewPdfPath) {
      try {
        await pyCallStrict('attach_pdf', { id: savedId, source_path: pendingNewPdfPath });
      } catch (pdfErr) {
        App.toast('Το τιμολόγιο αποθηκεύτηκε, αλλά το PDF δεν επισυνάφθηκε: ' + pdfErr.message, 'warn');
      }
      pendingNewPdfPath = null;
    }
    closeEditModal();
    loadBrowse();
    window.reloadLookups();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

document.getElementById('edit-invoice-delete-btn').addEventListener('click', async () => {
  const invoiceId = parseInt(document.getElementById('edit-invoice-id').value, 10);
  const supplier = document.getElementById('edit-supplier-name').value || '—';
  const docNumber = document.getElementById('edit-doc-number').value || '—';
  const docDate = document.getElementById('edit-doc-date').value || '—';
  const ok = await App.confirmAsync(
    `Διαγραφή ΟΛΟΚΛΗΡΟΥ του τιμολογίου «${docNumber}» (${docDate}, ${supplier}) — ` +
    `μαζί με όλες τις γραμμές του και το αρχείο PDF του. Δεν αναιρείται. Συνέχεια;`
  );
  if (!ok) return;
  const unlock = _lock(document.getElementById('edit-invoice-delete-btn'));
  try {
    await pyCallStrict('delete_invoice', { id: invoiceId });
    App.toast('Το τιμολόγιο διαγράφηκε', 'ok');
    closeEditModal();
    loadBrowse();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

loadBrowse();
