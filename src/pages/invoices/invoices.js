import { escapeHtml, _lock, fmtMoney, fmtDate, todayInput } from '../../../js/utils.js';

let itemRowSeq = 0;
let pickedPdfSourcePath = null; // απόλυτη διαδρομή επιλεγμένου αρχείου, ΠΡΙΝ την υιοθέτηση (μετακίνηση) στο pdf_store
let currentStoredPdfFilename = null; // όνομα ήδη υιοθετημένου PDF (μόνο σε edit)

function setPdfUiIdle() {
  pickedPdfSourcePath = null;
  currentStoredPdfFilename = null;
  document.getElementById('pdf-status').textContent = 'Κανένα αρχείο';
  document.getElementById('open-pdf-btn').style.display = 'none';
}

document.getElementById('pick-pdf-btn').addEventListener('click', async () => {
  const filePath = await window.api.pickPdfFile();
  if (!filePath) return;
  pickedPdfSourcePath = filePath;
  document.getElementById('pdf-status').textContent = filePath.split(/[\\/]/).pop();
  document.getElementById('open-pdf-btn').style.display = 'none';
});

document.getElementById('open-pdf-btn').addEventListener('click', async () => {
  if (!currentStoredPdfFilename) return;
  const r = await window.api.openStoredFile(currentStoredPdfFilename);
  if (!r.ok) App.toast('Δεν ήταν δυνατό το άνοιγμα: ' + r.error, 'fail');
});

function supplierOptions(selectedId) {
  return window.AppState.suppliers.map(s =>
    `<option value="${s.id}" ${s.id == selectedId ? 'selected' : ''}>${escapeHtml(s.name)}</option>`
  ).join('');
}

function populateSupplierDropdowns() {
  document.getElementById('inv-supplier').innerHTML = '<option value="">— Επιλέξτε —</option>' + supplierOptions();
  document.getElementById('filter-supplier').innerHTML = '<option value="">Όλοι</option>' + supplierOptions();
}

function addItemRow(item) {
  const id = ++itemRowSeq;
  const tr = document.createElement('tr');
  tr.dataset.rowId = id;
  tr.innerHTML = `
    <td><input type="text" class="it-code" value="${escapeHtml(item?.code || '')}"></td>
    <td><input type="text" class="it-desc" value="${escapeHtml(item?.description || '')}"></td>
    <td><input type="text" class="it-unit" value="${escapeHtml(item?.unit || '')}" style="width:70px"></td>
    <td><input type="number" step="any" class="it-qty" value="${item?.quantity ?? ''}" style="width:80px"></td>
    <td><input type="number" step="any" class="it-price" value="${item?.unit_price ?? ''}" style="width:90px"></td>
    <td><input type="number" step="any" class="it-value" value="${item?.value ?? ''}" style="width:90px"></td>
    <td><span class="items-remove-btn" title="Αφαίρεση">✕</span></td>
  `;
  tr.querySelector('.items-remove-btn').addEventListener('click', () => tr.remove());
  document.getElementById('items-body').appendChild(tr);
}

function readItemRows() {
  return [...document.getElementById('items-body').querySelectorAll('tr')].map(tr => ({
    code: tr.querySelector('.it-code').value.trim() || null,
    description: tr.querySelector('.it-desc').value.trim(),
    unit: tr.querySelector('.it-unit').value.trim() || null,
    quantity: tr.querySelector('.it-qty').value ? parseFloat(tr.querySelector('.it-qty').value) : null,
    unit_price: tr.querySelector('.it-price').value ? parseFloat(tr.querySelector('.it-price').value) : null,
    value: tr.querySelector('.it-value').value ? parseFloat(tr.querySelector('.it-value').value) : null,
  })).filter(it => it.description);
}

function clearForm() {
  document.getElementById('inv-id').value = '';
  document.getElementById('invoice-form').reset();
  document.getElementById('inv-doc-date').value = todayInput();
  document.getElementById('items-body').innerHTML = '';
  document.getElementById('inv-form-title').textContent = 'Νέο Τιμολόγιο';
  setPdfUiIdle();
}

async function editInvoice(id) {
  const inv = await pyCall('get_invoice', { id });
  if (!inv) return;
  document.getElementById('inv-id').value = inv.id;
  document.getElementById('inv-supplier').value = inv.supplier_id || '';
  document.getElementById('inv-doc-type').value = inv.doc_type || '';
  document.getElementById('inv-doc-number').value = inv.doc_number || '';
  document.getElementById('inv-doc-date').value = inv.doc_date || '';
  document.getElementById('inv-doc-time').value = inv.doc_time || '';
  document.getElementById('inv-payment').value = inv.payment_method || '';
  document.getElementById('inv-net').value = inv.net_amount ?? '';
  document.getElementById('inv-vat').value = inv.vat_amount ?? '';
  document.getElementById('inv-total').value = inv.total_amount ?? '';
  document.getElementById('inv-notes').value = inv.notes || '';
  document.getElementById('items-body').innerHTML = '';
  (inv.items || []).forEach(addItemRow);
  document.getElementById('inv-form-title').textContent = `Επεξεργασία Τιμολογίου #${inv.id}`;

  pickedPdfSourcePath = null;
  if (inv.pdf_available) {
    currentStoredPdfFilename = inv.source_pdf_filename;
    document.getElementById('pdf-status').textContent = inv.source_pdf_filename;
    document.getElementById('open-pdf-btn').style.display = '';
  } else {
    currentStoredPdfFilename = null;
    document.getElementById('pdf-status').textContent = 'Κανένα αρχείο';
    document.getElementById('open-pdf-btn').style.display = 'none';
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadList() {
  const date_from = document.getElementById('filter-from').value || undefined;
  const date_to = document.getElementById('filter-to').value || undefined;
  const supplier_id = document.getElementById('filter-supplier').value || undefined;

  const rows = await pyCall('get_invoices', { date_from, date_to, supplier_id }) || [];
  const body = document.getElementById('invoices-body');
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="icon">📄</div><p>Δεν βρέθηκαν τιμολόγια.</p></div></td></tr>`;
    return;
  }
  body.innerHTML = rows.map(r => `
    <tr>
      <td>${fmtDate(r.doc_date)}</td>
      <td>${escapeHtml(r.supplier_name || '—')}</td>
      <td>${escapeHtml(r.doc_type || '')}</td>
      <td class="mono">${escapeHtml(r.doc_number || '')}</td>
      <td class="text-right mono">${fmtMoney(r.total_amount)}</td>
      <td>
        <button class="btn btn-outline btn-sm" data-edit="${r.id}">Επεξεργασία</button>
        <button class="btn btn-danger btn-sm" data-del="${r.id}">Διαγραφή</button>
      </td>
    </tr>
  `).join('');

  body.querySelectorAll('[data-edit]').forEach(btn =>
    btn.addEventListener('click', () => editInvoice(parseInt(btn.dataset.edit, 10)))
  );
  body.querySelectorAll('[data-del]').forEach(btn =>
    btn.addEventListener('click', () => {
      App.confirmDelete('Διαγραφή αυτού του τιμολογίου;', async () => {
        await pyCallStrict('delete_invoice', { id: parseInt(btn.dataset.del, 10) });
        App.toast('Το τιμολόγιο διαγράφηκε', 'ok');
        loadList();
      });
    })
  );
}

document.getElementById('invoice-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const supplier_id = document.getElementById('inv-supplier').value;
  const doc_date = document.getElementById('inv-doc-date').value;
  if (!supplier_id) { App.toast('Επιλέξτε προμηθευτή', 'fail'); return; }
  if (!doc_date) { App.toast('Η ημερομηνία είναι υποχρεωτική', 'fail'); return; }

  const header = {
    supplier_id: parseInt(supplier_id, 10),
    doc_type: document.getElementById('inv-doc-type').value.trim() || null,
    doc_number: document.getElementById('inv-doc-number').value.trim() || null,
    doc_date,
    doc_time: document.getElementById('inv-doc-time').value || null,
    payment_method: document.getElementById('inv-payment').value.trim() || null,
    net_amount: document.getElementById('inv-net').value ? parseFloat(document.getElementById('inv-net').value) : null,
    vat_amount: document.getElementById('inv-vat').value ? parseFloat(document.getElementById('inv-vat').value) : null,
    total_amount: document.getElementById('inv-total').value ? parseFloat(document.getElementById('inv-total').value) : null,
    notes: document.getElementById('inv-notes').value.trim() || null,
  };
  const items = readItemRows();
  const id = document.getElementById('inv-id').value;

  const unlock = _lock(document.getElementById('inv-save-btn'));
  try {
    let savedId;
    if (id) {
      savedId = parseInt(id, 10);
      await pyCallStrict('update_invoice', { id: savedId, header, items });
      App.toast('Το τιμολόγιο ενημερώθηκε', 'ok');
    } else {
      const res = await pyCallStrict('add_invoice', { header, items });
      savedId = res.id;
      App.toast('Το τιμολόγιο προστέθηκε', 'ok');
    }
    if (pickedPdfSourcePath) {
      try {
        await pyCallStrict('attach_pdf', { id: savedId, source_path: pickedPdfSourcePath });
      } catch (pdfErr) {
        App.toast('Το τιμολόγιο αποθηκεύτηκε, αλλά το PDF δεν επισυνάφθηκε: ' + pdfErr.message, 'warn');
      }
    }
    clearForm();
    loadList();
  } catch (err) {
    App.toast(err.message, 'fail');
  } finally {
    unlock();
  }
});

document.getElementById('add-item-btn').addEventListener('click', () => addItemRow());
document.getElementById('inv-clear-btn').addEventListener('click', clearForm);
document.getElementById('filter-btn').addEventListener('click', loadList);
document.getElementById('filter-clear-btn').addEventListener('click', () => {
  document.getElementById('filter-from').value = '';
  document.getElementById('filter-to').value = '';
  document.getElementById('filter-supplier').value = '';
  loadList();
});

populateSupplierDropdowns();
clearForm();
loadList();
