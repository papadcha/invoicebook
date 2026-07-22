import { fmtMoney } from '../../../js/utils.js';

const MONTH_NAMES = ['Ιαν','Φεβ','Μαρ','Απρ','Μάι','Ιούν','Ιούλ','Αύγ','Σεπ','Οκτ','Νοέ','Δεκ'];

async function load() {
  const rows = await pyCall('get_summary', {}) || [];

  let invoiceCount = 0, netTotal = 0, vatTotal = 0, grandTotal = 0;
  const body = document.getElementById('dash-months-body');
  body.innerHTML = '';

  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="icon">📄</div><p>Δεν υπάρχουν ακόμα τιμολόγια.</p></div></td></tr>`;
  }

  for (const r of rows) {
    invoiceCount += r.invoice_count || 0;
    netTotal += r.net_total || 0;
    vatTotal += r.vat_total || 0;
    grandTotal += r.grand_total || 0;

    const monthLabel = r.yr && r.mo ? `${MONTH_NAMES[parseInt(r.mo, 10) - 1]} ${r.yr}` : '—';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${monthLabel}</td>
      <td class="text-right mono">${r.invoice_count}</td>
      <td class="text-right mono">${fmtMoney(r.net_total)}</td>
      <td class="text-right mono">${fmtMoney(r.vat_total)}</td>
      <td class="text-right mono">${fmtMoney(r.grand_total)}</td>
    `;
    body.appendChild(tr);
  }

  document.getElementById('stat-invoices').textContent = invoiceCount;
  document.getElementById('stat-net').textContent = fmtMoney(netTotal);
  document.getElementById('stat-vat').textContent = fmtMoney(vatTotal);
  document.getElementById('stat-total').textContent = fmtMoney(grandTotal);
}

load();
