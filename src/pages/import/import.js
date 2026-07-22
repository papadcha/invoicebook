import { escapeHtml, fmtMoney, fmtDate, _lock } from '../../../js/utils.js';

let pickedFilePath = null;

document.getElementById('pick-file-btn').addEventListener('click', async () => {
  const filePath = await window.api.openImportFile();
  if (!filePath) return;
  pickedFilePath = filePath;
  document.getElementById('picked-file-name').textContent = filePath.split(/[\\/]/).pop();
  document.getElementById('do-import-btn').disabled = false;
});

document.getElementById('do-import-btn').addEventListener('click', async () => {
  if (!pickedFilePath) return;
  const batch_label = document.getElementById('batch-label').value.trim() || null;
  const unlock = _lock(document.getElementById('do-import-btn'));
  try {
    const rows = await pyCallStrict('import_staging_file', { file_path: pickedFilePath, batch_label });
    App.toast(`Εισήχθησαν ${rows.length} γραμμές για επιβεβαίωση`, 'ok');
    pickedFilePath = null;
    document.getElementById('picked-file-name').textContent = 'Κανένα αρχείο';
    document.getElementById('do-import-btn').disabled = true;
    loadStaging();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

async function loadStaging() {
  const rows = await pyCall('get_staging_batch', { status: 'pending' }) || [];
  const body = document.getElementById('staging-body');
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="icon">📂</div><p>Δεν υπάρχουν γραμμές σε αναμονή.</p></div></td></tr>`;
    return;
  }
  body.innerHTML = rows.map(r => {
    const d = r.data;
    return `
      <tr data-id="${r.id}">
        <td>${escapeHtml(r.batch_label || '—')}</td>
        <td>${escapeHtml(d.supplier_name || '—')}</td>
        <td class="mono">${escapeHtml(d.doc_number || '')}</td>
        <td>${fmtDate(d.doc_date)}</td>
        <td class="text-right mono">${fmtMoney(d.total_amount)}</td>
        <td>
          <button class="btn btn-success btn-sm" data-confirm="${r.id}">Επιβεβαίωση</button>
          <button class="btn btn-danger btn-sm" data-reject="${r.id}">Απόρριψη</button>
        </td>
      </tr>
    `;
  }).join('');

  body.querySelectorAll('[data-confirm]').forEach(btn => btn.addEventListener('click', async () => {
    const stagingId = parseInt(btn.dataset.confirm, 10);
    const row = rows.find(r => r.id === stagingId);
    try {
      const res = await pyCallStrict('confirm_staging_row', { id: stagingId });
      // Αν η γραμμή εισαγωγής έχει καταγράψει και τη διαδρομή του αρχικού
      // σαρωμένου PDF (source_pdf_path), υιοθέτησέ το τώρα — μετακίνηση,
      // όχι αντιγραφή, ίδιο μηχανισμό με τη χειροκίνητη επισύναψη.
      if (row?.data?.source_pdf_path) {
        try {
          await pyCallStrict('attach_pdf', { id: res.invoice_id, source_path: row.data.source_pdf_path });
        } catch (pdfErr) {
          App.toast('Καταχωρήθηκε, αλλά το PDF δεν επισυνάφθηκε: ' + pdfErr.message, 'warn');
        }
      }
      App.toast('Καταχωρήθηκε ως τιμολόγιο', 'ok');
      loadStaging();
    } catch (e) {
      App.toast(e.message, 'fail');
    }
  }));
  body.querySelectorAll('[data-reject]').forEach(btn => btn.addEventListener('click', () => {
    App.confirmDelete('Απόρριψη αυτής της γραμμής εισαγωγής;', async () => {
      await pyCallStrict('reject_staging_row', { id: parseInt(btn.dataset.reject, 10) });
      App.toast('Η γραμμή απορρίφθηκε', 'ok');
      loadStaging();
    });
  }));
}

loadStaging();
