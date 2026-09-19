// ── HTML ESCAPING ────────────────────────────────────────────────────────────
// Χρήση πριν την εισαγωγή εξωτερικού κειμένου (π.χ. από import) σε innerHTML.
export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function _lock(btn) {
  if (!btn) return () => {};
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '⏳ …';
  return () => { btn.disabled = false; btn.innerHTML = orig; };
}

export function fmtDate(s) { if (!s) return ''; const [y,m,d] = (s||'').split('-'); return d?`${d}/${m}/${y}`:s; }
export function fmtMoney(n) { return (Number(n)||0).toLocaleString('el-GR', {minimumFractionDigits:2, maximumFractionDigits:2}) + ' €'; }
export function todayInput() { return new Date().toISOString().slice(0,10); }

export function fmtDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString('el-GR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// π.χ. 1234.5 -> "1.234,50" (ελληνική μορφή: τελεία χιλιάδων, κόμμα δεκαδικών)
export function fmtQty(n) {
  if (n === null || n === undefined || n === '') return '';
  return Number(n).toLocaleString('el-GR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ── ΚΑΝΟΝΙΚΟΠΟΙΗΣΗ ΕΛΛΗΝΙΚΩΝ ─────────────────────────────────────────────────
// Ίδια λογική με το intake-tool's js/import.js (πλέον ενοποιημένο εδώ, αφού και
// οι δύο νέες σελίδες — Εισαγωγή, Συγχωνεύσεις — τη χρειάζονται).
export function normalizeGreek(s) {
  // .replace(/ς/g, 'σ'): το JS toLowerCase() κάνει το τελικό Σ -> ς (U+03C2)
  // μόνο όταν βρίσκεται στο τέλος του string — χωρίς αυτό, η αναζήτηση δεν
  // ταιριάζει λέξεις που στο ερώτημα καταλήγουν σε Σ με λέξεις που το ίδιο
  // γράμμα βρίσκεται στη μέση.
  return (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/ς/g, 'σ').trim();
}

export function normalizeCategory(s) {
  if (!s) return s;
  return s.trim().replace(/\s*\/\s*/g, '/');
}

// Ελληνικά κεφαλαία γράμματα οπτικά πανομοιότυπα με λατινικά (π.χ. πληκτρολόγιο
// σε ελληνική διάταξη κατά την πληκτρολόγηση πινακίδας μηχανήματος).
const MACHINE_HOMOGLYPHS = {
  'Α': 'A', 'Β': 'B', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'H', 'Ι': 'I', 'Κ': 'K',
  'Μ': 'M', 'Ν': 'N', 'Ο': 'O', 'Ρ': 'P', 'Τ': 'T', 'Υ': 'Y', 'Χ': 'X',
};
export function normalizeMachineCode(s) {
  return (s || '')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .split('').map(ch => MACHINE_HOMOGLYPHS[ch] || ch).join('')
    .replace(/[^A-Z0-9Α-Ω]/g, '');
}

// Custom autocomplete dropdown — αντικαθιστά το native <datalist>, το οποίο δεν
// scrollάρει αξιόπιστα με πολλά αποτελέσματα (βλ. intake-tool's js/utils.js,
// ίδιο πρόβλημα βρέθηκε εκεί 2026-09-16 στο πεδίο μηχανήματος). Ένα μόνο,
// κοινό (module-level) dropdown div επαναχρησιμοποιείται από όλες τις κλήσεις.
let _acDropdown = null;
let _acItems = [];
let _acActiveIndex = -1;
let _acInput = null;
let _acGetOptions = null;
let _acNormalize = null;

function _acEnsureDropdown() {
  if (_acDropdown) return _acDropdown;
  _acDropdown = document.createElement('div');
  _acDropdown.className = 'ac-dropdown';
  document.body.appendChild(_acDropdown);
  _acDropdown.addEventListener('mousedown', (e) => {
    const item = e.target.closest('[data-ac-idx]');
    if (!item) return;
    e.preventDefault();
    _acSelect(parseInt(item.dataset.acIdx, 10));
  });
  return _acDropdown;
}

function _acClose() {
  if (_acDropdown) _acDropdown.style.display = 'none';
  _acItems = [];
  _acActiveIndex = -1;
  _acInput = null;
}

function _acPosition(input) {
  const r = input.getBoundingClientRect();
  _acDropdown.style.left = `${r.left}px`;
  _acDropdown.style.top = `${r.bottom + 2}px`;
  _acDropdown.style.width = `${Math.max(r.width, 200)}px`;
}

function _acRender(input, query) {
  const q = _acNormalize(query || '');
  const seen = new Set();
  const filtered = [];
  for (const opt of (_acGetOptions() || [])) {
    if (!opt || seen.has(opt)) continue;
    if (!q || _acNormalize(opt).includes(q)) { filtered.push(opt); seen.add(opt); }
  }
  _acItems = filtered;
  _acActiveIndex = -1;
  const dd = _acEnsureDropdown();
  if (!filtered.length) { dd.style.display = 'none'; return; }
  dd.innerHTML = filtered.map((opt, i) => `<div class="ac-item" data-ac-idx="${i}">${escapeHtml(opt)}</div>`).join('');
  _acPosition(input);
  dd.style.display = 'block';
}

function _acSelect(idx) {
  if (idx < 0 || idx >= _acItems.length || !_acInput) return;
  const input = _acInput;
  input.value = _acItems[idx];
  _acClose();
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

function _acMove(delta) {
  if (!_acItems.length) return;
  _acActiveIndex = (_acActiveIndex + delta + _acItems.length) % _acItems.length;
  [..._acDropdown.children].forEach((el, i) => el.classList.toggle('active', i === _acActiveIndex));
  const activeEl = _acDropdown.children[_acActiveIndex];
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

// containerEl/selector: event-delegation σε σταθερό container — δουλεύει και
// για γραμμές που μπαίνουν αργότερα μέσω innerHTML. getOptions: συνάρτηση
// χωρίς ορίσματα που επιστρέφει το ΤΡΕΧΟΝ array από strings (όχι snapshot).
export function attachAutocomplete(containerEl, selector, getOptions, { normalize } = {}) {
  const norm = normalize || (s => (s || '').toLowerCase());
  containerEl.addEventListener('focusin', (e) => {
    const input = e.target.closest(selector);
    if (!input) return;
    _acInput = input;
    _acGetOptions = getOptions;
    _acNormalize = norm;
    _acRender(input, input.value);
  });
  containerEl.addEventListener('input', (e) => {
    const input = e.target.closest(selector);
    if (!input || input !== _acInput) return;
    _acRender(input, input.value);
  });
  containerEl.addEventListener('focusout', (e) => {
    const input = e.target.closest(selector);
    if (!input || input !== _acInput) return;
    _acClose();
  });
  containerEl.addEventListener('keydown', (e) => {
    const input = e.target.closest(selector);
    if (!input || input !== _acInput || !_acDropdown || _acDropdown.style.display === 'none') return;
    if (e.key === 'ArrowDown') { e.preventDefault(); _acMove(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); _acMove(-1); }
    else if (e.key === 'Enter') { if (_acActiveIndex >= 0) { e.preventDefault(); _acSelect(_acActiveIndex); } }
    else if (e.key === 'Escape') { _acClose(); }
  });
}
window.addEventListener('scroll', () => { if (_acInput) _acPosition(_acInput); }, true);
window.addEventListener('resize', () => { if (_acInput) _acPosition(_acInput); });
