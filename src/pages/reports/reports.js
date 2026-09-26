import {
  escapeHtml, fmtQty, fmtMoney,
  normalizeGreek, normalizeMachineCode, attachAutocomplete,
} from '../../../js/utils.js';

const MONTH_NAMES = ['Ιαν','Φεβ','Μαρ','Απρ','Μάι','Ιούν','Ιούλ','Αύγ','Σεπ','Οκτ','Νοέ','Δεκ'];

function normalizeVat(v) {
  if (!v) return null;
  v = String(v).trim().toUpperCase().replace(/[\s\-]/g, '');
  if (v.startsWith('EL')) v = v.slice(2);
  return v || null;
}

let reportsRows = [];
let reportsCategoryFilter = '';
// '' = κανένα φίλτρο. Προμηθευτής: normalizeVat(vat_number), ή 'name:<normalizeGreek(name)>'
// για τους ελάχιστους προμηθευτές χωρίς ΑΦΜ. Μηχάνημα: normalizeMachineCode(name).
// Περιγραφή: normalizeGreek(πρώτα 1-2 tokens). Γεμίζουν μόνο όταν το κείμενο του πεδίου
// ταιριάζει ΑΚΡΙΒΩΣ (κανονικοποιημένο) με ήδη υπάρχοντα προμηθευτή/μηχάνημα/ομάδα
// περιγραφής — βλ. resolveSupplierFilter/resolveMachineFilter/resolveDescriptionFilter.
let reportsSupplierVatFilter = '';
let reportsMachineNameFilter = '';
let reportsDescriptionGroupFilter = '';
// normalizeGreek(group key) -> label προς εμφάνιση (πρώτη εμφάνιση, πρωτότυπη μορφή).
// Ξαναχτίζεται όποτε αλλάζει η κατηγορία, ώστε οι προτάσεις αυτόματης συμπλήρωσης να
// αφορούν μόνο την επιλεγμένη κατηγορία (αλλιώς η λίστα θα ήταν τεράστια/άσχετη).
let reportsDescriptionGroups = new Map();

function descriptionGroupLabel(desc) {
  if (!desc) return '';
  const words = desc.trim().split(/\s+/);
  return words.slice(0, Math.min(2, words.length)).join(' ');
}
function descriptionGroupKey(desc) {
  return normalizeGreek(descriptionGroupLabel(desc));
}

function resolveSupplierFilter(text) {
  if (!text) return '';
  const norm = normalizeGreek(text);
  const match = (window.AppState.suppliers || []).find(s => normalizeGreek(s.name) === norm);
  if (!match) return null;
  return match.vat_number ? normalizeVat(match.vat_number) : `name:${normalizeGreek(match.name)}`;
}

function resolveMachineFilter(text) {
  if (!text) return '';
  const norm = normalizeMachineCode(text);
  if (!norm) return null;
  const match = (window.AppState.machines || []).find(m => normalizeMachineCode(m.name) === norm);
  return match ? norm : null;
}

function resolveDescriptionFilter(text) {
  if (!text) return '';
  const norm = normalizeGreek(text.trim());
  return reportsDescriptionGroups.has(norm) ? norm : null;
}

function rebuildDescriptionGroups() {
  reportsDescriptionGroups = new Map();
  const scoped = reportsCategoryFilter ? reportsRows.filter(r => r.category === reportsCategoryFilter) : reportsRows;
  for (const r of scoped) {
    const label = descriptionGroupLabel(r.description);
    if (!label) continue;
    const key = normalizeGreek(label);
    if (!reportsDescriptionGroups.has(key)) reportsDescriptionGroups.set(key, label);
  }
}

function populateCategoryOptions() {
  const select = document.getElementById('reports-category-filter');
  const categories = (window.AppState.categories || []).slice().sort((a, b) => a.localeCompare(b, 'el'));
  select.innerHTML = `<option value="">Όλες</option>` +
    categories.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
  select.value = reportsCategoryFilter;
}

async function loadReports() {
  reportsRows = await pyCall('list_invoice_items_by_category', { category: null }) || [];
  populateCategoryOptions();
  rebuildDescriptionGroups();
  applyReportsFilters();
}

function applyReportsFilters() {
  const dateFrom = document.getElementById('reports-date-from').value || null;
  const dateTo = document.getElementById('reports-date-to').value || null;

  let filtered = reportsRows;
  if (dateFrom) filtered = filtered.filter(r => r.doc_date && r.doc_date >= dateFrom);
  if (dateTo) filtered = filtered.filter(r => r.doc_date && r.doc_date <= dateTo);
  if (reportsCategoryFilter) filtered = filtered.filter(r => r.category === reportsCategoryFilter);
  if (reportsSupplierVatFilter) filtered = filtered.filter(r => reportsSupplierVatFilter.startsWith('name:')
    ? `name:${normalizeGreek(r.supplier_name)}` === reportsSupplierVatFilter
    : normalizeVat(r.supplier_vat) === reportsSupplierVatFilter);
  if (reportsMachineNameFilter) filtered = filtered.filter(r => normalizeMachineCode(r.machine_name) === reportsMachineNameFilter);
  if (reportsDescriptionGroupFilter) filtered = filtered.filter(r => descriptionGroupKey(r.description) === reportsDescriptionGroupFilter);

  renderMonthlyReport(filtered);
}

// Δύο λειτουργίες ανάλογα αν είναι ενεργό κάποιο φίλτρο σε επίπεδο ΓΡΑΜΜΗΣ
// (κατηγορία/μηχάνημα/περιγραφή — lineLevel) ή όχι:
// - lineLevel: το header amount (net/vat/total) αφορά ΟΛΟΚΛΗΡΟ το τιμολόγιο, όχι μόνο τις
//   γραμμές που ταιριάζουν στο φίλτρο — δεν έχει νόημα να αθροιστεί. Πηγή γίνεται η ίδια η
//   γραμμή (quantity/value), χωρίς dedupe.
// - χωρίς lineLevel (μόνο π.χ. φίλτρο προμηθευτή, που περιορίζει σε ΟΛΟΚΛΗΡΑ τιμολόγια):
//   header amounts — ένα τιμολόγιο εμφανίζεται ΠΟΛΛΕΣ φορές (μία ανά γραμμή) στα rows, άρα
//   ΠΡΕΠΕΙ να γίνει dedupe ανά invoice_id πριν το άθροισμα, αλλιώς πολλαπλασιάζεται το ποσό
//   όσες γραμμές έχει το τιμολόγιο.
function computeMonthlyReport(rows) {
  const lineLevel = !!(reportsCategoryFilter || reportsMachineNameFilter || reportsDescriptionGroupFilter);
  // Η ΠΟΣΟΤΗΤΑ έχει νόημα να αθροιστεί μόνο όταν είναι ενεργό το φίλτρο Περιγραφής —
  // δηλαδή όταν οι γραμμές είναι πραγματικά το ΙΔΙΟ προϊόν. Κατηγορία/Μηχάνημα από μόνα
  // τους ΔΕΝ αρκούν (ακόμα κι αν όλες οι γραμμές έχουν την ίδια μονάδα π.χ. ΤΕΜ, μπορεί
  // να είναι εντελώς διαφορετικά πράγματα — π.χ. βίδες + μπιτόνια — άρα ένα άθροισμα
  // ποσότητας θα ήταν εξίσου άσκοπο με το ανάμειξη μονάδων). Η ΑΞΙΑ (€) παραμένει πάντα
  // αθροίσιμη ανεξαρτήτως προϊόντος, γι' αυτό δεν έχει το ίδιο περιορισμό.
  const qtyMeaningful = !!reportsDescriptionGroupFilter;
  const months = new Map();

  const seenInvoicePerMonth = new Set();
  for (const r of rows) {
    if (!r.doc_date) continue;
    const key = r.doc_date.slice(0, 7); // 'YYYY-MM'
    if (!months.has(key)) {
      months.set(key, { key, invoiceIds: new Set(), netTotal: 0, vatTotal: 0, grandTotal: 0, qtyByUnit: new Map(), valueTotal: 0 });
    }
    const m = months.get(key);
    m.invoiceIds.add(r.invoice_id);

    if (lineLevel) {
      if (qtyMeaningful) {
        // Άθροισμα ΑΝΑ ΜΟΝΑΔΑ (unit) ακόμα κι εδώ, προληπτικά (formatting-level ασφάλεια) —
        // η ίδια η ομάδα περιγραφής πρακτικά έχει ήδη μία μονάδα, βλ. σχόλιο πιο πάνω.
        const unit = r.unit || '';
        m.qtyByUnit.set(unit, (m.qtyByUnit.get(unit) || 0) + (r.quantity || 0));
      }
      m.valueTotal += r.value || 0;
    } else {
      const dedupeKey = `${key}:${r.invoice_id}`;
      if (!seenInvoicePerMonth.has(dedupeKey)) {
        seenInvoicePerMonth.add(dedupeKey);
        m.netTotal += r.net_amount || 0;
        m.vatTotal += r.vat_amount || 0;
        m.grandTotal += r.total_amount || 0;
      }
    }
  }

  const list = Array.from(months.values()).sort((a, b) => b.key.localeCompare(a.key));
  return { lineLevel, qtyMeaningful, months: list };
}

// π.χ. Map{'L'=>150, 'kg'=>20} -> "150,00 L, 20,00 kg" — ξεχωριστό άθροισμα ανά μονάδα.
function fmtQtyByUnit(map) {
  if (!map.size) return '—';
  return Array.from(map.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([unit, qty]) => `${fmtQty(qty)}${unit ? ' ' + unit : ''}`)
    .join(', ');
}

function renderMonthlyReport(rows) {
  const { lineLevel, qtyMeaningful, months } = computeMonthlyReport(rows);
  const table = document.getElementById('reports-table');
  const body = document.getElementById('reports-body');
  const scopeNote = document.getElementById('reports-scope-note');
  const cols = !lineLevel ? 5 : (qtyMeaningful ? 4 : 3);

  scopeNote.textContent = !lineLevel
    ? 'Ποσά τιμολογίου (καθ. αξία/ΦΠΑ/σύνολο), ένα τιμολόγιο μετράει μία φορά'
    : qtyMeaningful
      ? 'Ποσότητα/αξία ανά γραμμή (όχι τα ποσά τιμολογίου, αφορούν ολόκληρο το παραστατικό) — ενεργό φίλτρο περιγραφής'
      : 'Αξία ανά γραμμή, χωρίς ποσότητα (όχι τα ποσά τιμολογίου, αφορούν ολόκληρο το παραστατικό) — η ποσότητα δεν αθροίζεται χωρίς ενεργό φίλτρο περιγραφής, αφού κατηγορία/μηχάνημα από μόνα τους μπορεί να καλύπτουν εντελώς διαφορετικά προϊόντα';

  table.querySelector('thead').innerHTML = !lineLevel
    ? `<tr><th>Μήνας</th><th class="text-right">Τιμολόγια</th><th class="text-right">Καθαρή Αξία</th><th class="text-right">ΦΠΑ</th><th class="text-right">Σύνολο</th></tr>`
    : qtyMeaningful
      ? `<tr><th>Μήνας</th><th class="text-right">Τιμολόγια</th><th class="text-right">Ποσότητα</th><th class="text-right">Αξία</th></tr>`
      : `<tr><th>Μήνας</th><th class="text-right">Τιμολόγια</th><th class="text-right">Αξία</th></tr>`;

  if (!months.length) {
    body.innerHTML = `<tr><td colspan="${cols}"><div class="empty-state"><div class="icon">📄</div><p>Καμία γραμμή στο τρέχον φίλτρο.</p></div></td></tr>`;
  } else {
    body.innerHTML = months.map(m => {
      const [yr, mo] = m.key.split('-');
      const label = `${MONTH_NAMES[parseInt(mo, 10) - 1]} ${yr}`;
      if (!lineLevel) {
        return `<tr><td>${label}</td><td class="text-right mono">${m.invoiceIds.size}</td><td class="text-right mono">${fmtMoney(m.netTotal)}</td><td class="text-right mono">${fmtMoney(m.vatTotal)}</td><td class="text-right mono">${fmtMoney(m.grandTotal)}</td></tr>`;
      }
      return qtyMeaningful
        ? `<tr><td>${label}</td><td class="text-right mono">${m.invoiceIds.size}</td><td class="text-right mono">${escapeHtml(fmtQtyByUnit(m.qtyByUnit))}</td><td class="text-right mono">${fmtMoney(m.valueTotal)}</td></tr>`
        : `<tr><td>${label}</td><td class="text-right mono">${m.invoiceIds.size}</td><td class="text-right mono">${fmtMoney(m.valueTotal)}</td></tr>`;
    }).join('');
  }

  const totalInvoices = new Set(months.flatMap(m => Array.from(m.invoiceIds))).size;
  const grandQtyByUnit = new Map();
  for (const m of months) {
    for (const [unit, qty] of m.qtyByUnit) grandQtyByUnit.set(unit, (grandQtyByUnit.get(unit) || 0) + qty);
  }
  document.getElementById('reports-stats').innerHTML = !lineLevel
    ? `
      <div class="stat-card"><div class="stat-val">${totalInvoices}</div><div class="stat-label">Τιμολόγια</div></div>
      <div class="stat-card"><div class="stat-val">${fmtMoney(months.reduce((s, m) => s + m.netTotal, 0))}</div><div class="stat-label">Καθαρή Αξία</div></div>
      <div class="stat-card"><div class="stat-val">${fmtMoney(months.reduce((s, m) => s + m.vatTotal, 0))}</div><div class="stat-label">ΦΠΑ</div></div>
      <div class="stat-card"><div class="stat-val">${fmtMoney(months.reduce((s, m) => s + m.grandTotal, 0))}</div><div class="stat-label">Σύνολο</div></div>
    `
    : qtyMeaningful
      ? `
        <div class="stat-card"><div class="stat-val">${totalInvoices}</div><div class="stat-label">Τιμολόγια</div></div>
        <div class="stat-card"><div class="stat-val">${escapeHtml(fmtQtyByUnit(grandQtyByUnit))}</div><div class="stat-label">Ποσότητα (σύνολο)</div></div>
        <div class="stat-card"><div class="stat-val">${fmtMoney(months.reduce((s, m) => s + m.valueTotal, 0))}</div><div class="stat-label">Αξία (σύνολο)</div></div>
      `
      : `
        <div class="stat-card"><div class="stat-val">${totalInvoices}</div><div class="stat-label">Τιμολόγια</div></div>
        <div class="stat-card"><div class="stat-val">${fmtMoney(months.reduce((s, m) => s + m.valueTotal, 0))}</div><div class="stat-label">Αξία (σύνολο)</div></div>
      `;
}

['reports-date-from', 'reports-date-to'].forEach(id => {
  document.getElementById(id).addEventListener('change', applyReportsFilters);
});

document.getElementById('reports-category-filter').addEventListener('change', (e) => {
  reportsCategoryFilter = e.target.value;
  rebuildDescriptionGroups();
  // Η επιλεγμένη ομάδα περιγραφής μπορεί να μην υπάρχει πια στη νέα κατηγορία.
  document.getElementById('reports-description-filter').value = '';
  reportsDescriptionGroupFilter = '';
  applyReportsFilters();
});

attachAutocomplete(document.getElementById('reports-extra-filters'), '#reports-supplier-filter', () => (window.AppState.suppliers || []).map(s => s.name), { normalize: normalizeGreek });
attachAutocomplete(document.getElementById('reports-extra-filters'), '#reports-machine-filter', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });
attachAutocomplete(document.getElementById('reports-extra-filters'), '#reports-description-filter', () => Array.from(reportsDescriptionGroups.values()), { normalize: normalizeGreek });

let reportsSupplierFilterDebounce = null;
document.getElementById('reports-supplier-filter').addEventListener('input', (e) => {
  clearTimeout(reportsSupplierFilterDebounce);
  reportsSupplierFilterDebounce = setTimeout(() => {
    reportsSupplierVatFilter = resolveSupplierFilter(e.target.value.trim()) || '';
    applyReportsFilters();
  }, 200);
});
let reportsMachineFilterDebounce = null;
document.getElementById('reports-machine-filter').addEventListener('input', (e) => {
  clearTimeout(reportsMachineFilterDebounce);
  reportsMachineFilterDebounce = setTimeout(() => {
    reportsMachineNameFilter = resolveMachineFilter(e.target.value.trim()) || '';
    applyReportsFilters();
  }, 200);
});
let reportsDescriptionFilterDebounce = null;
document.getElementById('reports-description-filter').addEventListener('input', (e) => {
  clearTimeout(reportsDescriptionFilterDebounce);
  reportsDescriptionFilterDebounce = setTimeout(() => {
    reportsDescriptionGroupFilter = resolveDescriptionFilter(e.target.value.trim()) || '';
    applyReportsFilters();
  }, 200);
});

loadReports();
