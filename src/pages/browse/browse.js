import { escapeHtml, fmtDate, fmtQty, normalizeGreek } from '../../../js/utils.js';

// ── ΣΤΑΘΕΡΕΣ ΣΟΒΑΡΟΤΗΤΑΣ ─────────────────────────────────────────────────────
const SEV_LABEL = { severe: 'Σοβαρό', moderate: 'Μέτριο', duplicate: 'Διπλότυπο', reviewed: 'Επιθεωρήθηκε' };
const SEV_BADGE_CLASS = { severe: 'rejected', duplicate: 'rejected', moderate: 'pending', reviewed: 'confirmed' };
const SEV_ACTIVE = { severe: true, duplicate: true, moderate: true };

function normalizeForSearch(s) {
  return normalizeGreek(s).replace(/[-/\s]+/g, '');
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
      <td>${sev ? `<span class="badge badge-${SEV_BADGE_CLASS[sev]}" title="${escapeHtml(browseReasonById[r.invoice_id] || '')}">${SEV_LABEL[sev]}</span>` : '—'}</td>
      <td>${r.pdf_available ? `<button class="btn btn-outline btn-sm" data-open-pdf="${escapeHtml(r.source_pdf_filename)}" title="Άνοιγμα PDF">📄</button>` : ''}</td>
    </tr>
  `;
  }).join('');

  body.querySelectorAll('[data-open-pdf]').forEach(btn => btn.addEventListener('click', async () => {
    const res = await window.api.openStoredFile(btn.dataset.openPdf);
    if (!res.ok) App.toast('Δεν ήταν δυνατό το άνοιγμα: ' + res.error, 'fail');
  }));
}

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

loadBrowse();
