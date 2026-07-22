import { escapeHtml, _lock } from '../../../js/utils.js';

async function load() {
  const suppliers = await pyCall('get_suppliers') || [];
  window.AppState.suppliers = suppliers;

  const body = document.getElementById('suppliers-body');
  if (!suppliers.length) {
    body.innerHTML = `<tr><td colspan="4"><div class="empty-state"><div class="icon">🏭</div><p>Δεν υπάρχουν ακόμα προμηθευτές.</p></div></td></tr>`;
    return;
  }
  body.innerHTML = suppliers.map(s => `
    <tr>
      <td>${escapeHtml(s.name)}</td>
      <td class="mono">${escapeHtml(s.vat_number || '—')}</td>
      <td>${escapeHtml(s.notes || '')}</td>
      <td>
        <button class="btn btn-outline btn-sm" data-edit="${s.id}">Επεξεργασία</button>
        <button class="btn btn-danger btn-sm" data-del="${s.id}">Διαγραφή</button>
      </td>
    </tr>
  `).join('');

  body.querySelectorAll('[data-edit]').forEach(btn => {
    btn.addEventListener('click', () => fillForm(suppliers.find(s => s.id == btn.dataset.edit)));
  });
  body.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', () => {
      const s = suppliers.find(x => x.id == btn.dataset.del);
      App.confirmDelete(`Διαγραφή προμηθευτή "${s.name}";`, async () => {
        try {
          await pyCallStrict('delete_supplier', { id: s.id });
          App.toast('Ο προμηθευτής διαγράφηκε', 'ok');
          load();
        } catch (e) {
          App.toast(e.message, 'fail');
        }
      });
    });
  });
}

function fillForm(s) {
  document.getElementById('sup-id').value = s.id;
  document.getElementById('sup-name').value = s.name || '';
  document.getElementById('sup-vat').value = s.vat_number || '';
  document.getElementById('sup-notes').value = s.notes || '';
}

function clearForm() {
  document.getElementById('sup-id').value = '';
  document.getElementById('supplier-form').reset();
}

document.getElementById('supplier-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('sup-name').value.trim();
  if (!name) { App.toast('Η επωνυμία είναι υποχρεωτική', 'fail'); return; }

  const id = document.getElementById('sup-id').value;
  const vat_number = document.getElementById('sup-vat').value.trim() || null;
  const notes = document.getElementById('sup-notes').value.trim() || null;

  const unlock = _lock(document.getElementById('sup-save-btn'));
  try {
    if (id) {
      await pyCallStrict('update_supplier', { id: parseInt(id, 10), name, vat_number, notes });
      App.toast('Ο προμηθευτής ενημερώθηκε', 'ok');
    } else {
      await pyCallStrict('add_supplier', { name, vat_number, notes });
      App.toast('Ο προμηθευτής προστέθηκε', 'ok');
    }
    clearForm();
    load();
  } catch (err) {
    App.toast(err.message, 'fail');
  } finally {
    unlock();
  }
});

document.getElementById('sup-clear-btn').addEventListener('click', clearForm);

load();
