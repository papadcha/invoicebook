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
