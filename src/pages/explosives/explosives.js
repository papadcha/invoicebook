import { escapeHtml, fmtDate, fmtDateTime, fmtQty, _lock } from '../../../js/utils.js';

let xvDocs = [];

// Κατάσταση εισαγωγής στο ExpVault+ (αποδεικτικό εισαγωγής): ✓ ok / ⚠ διαφορές / ⏳ εκκρεμεί επιβεβαίωση.
function importBadge(e) {
  if (e.import_status === 'ok') {
    return `<div style="color:var(--success);font-weight:600;" title="${escapeHtml(e.receipt_file || 'χειροκίνητη επιβεβαίωση')}">✓ Εισήχθη στο ExpVault+${e.imported_at ? ' ' + escapeHtml(fmtDateTime(e.imported_at)) : ''}${e.import_note ? ' — ' + escapeHtml(e.import_note) : ''}</div>`;
  }
  if (e.import_status === 'mismatch') {
    return `<div style="color:var(--warn, #b45309);font-weight:600;">⚠ Εισήχθη με διαφορές: ${escapeHtml(e.import_note || '')}</div>`;
  }
  return '<div style="color:var(--muted);">⏳ Δεν έχει επιβεβαιωθεί η εισαγωγή στο ExpVault+ (φόρτωσε απόδειξη)</div>';
}

async function loadExpvaultPreview() {
  const container = document.getElementById('xv-preview');
  container.innerHTML = '<p class="muted-sm">Φόρτωση…</p>';
  const date_from = document.getElementById('xv-date-from').value || null;
  const date_to = document.getElementById('xv-date-to').value || null;
  xvDocs = await pyCall('expvault_export_preview', { date_from, date_to }) || [];
  if (!xvDocs.length) {
    container.innerHTML = '<div class="empty-state"><div class="icon">💥</div><p>Κανένα τιμολόγιο με γραμμές «Εκρηκτικά» σε αυτό το διάστημα.</p></div>';
    return;
  }
  container.innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr>
        <th style="width:32px;"><input type="checkbox" id="xv-all" title="Επιλογή όλων (και όσων έχουν ήδη εξαχθεί)"></th>
        <th>Ημ/νία</th><th>Προμηθευτής</th><th>Αρ.</th><th>Τύπος expvault</th><th>Γραμμές</th><th>Παρατηρήσεις</th><th></th>
      </tr></thead>
      <tbody>${xvDocs.map((d, i) => `
        <tr>
          <td><input type="checkbox" class="xv-cb" data-i="${i}" ${!d.grammes.length ? 'disabled' : d.exported ? '' : 'checked'}></td>
          <td>${escapeHtml(fmtDate(d.export_date || d.doc_date))}</td>
          <td>${escapeHtml(d.export_promitheftis || d.supplier_name || '—')}</td>
          <td>${escapeHtml(d.export_number || d.doc_number || '—')}
            ${d.export_number && d.export_number !== d.doc_number ? `<div class="muted-sm" title="Το παραστατικό στο invoicebook">τιμ. ${escapeHtml(d.doc_number || '—')} · ${escapeHtml(fmtDate(d.doc_date))}</div>` : ''}</td>
          <td>
            <select class="xv-tipos" data-i="${i}">
              ${['ΕΙΣΑΓΩΓΗ', 'ΕΠΙΣΤΡΟΦΗ'].map(t => `<option ${t === d.tipos ? 'selected' : ''}>${t}</option>`).join('')}
            </select>
            <div class="muted-sm">${d.needs_check ? '⚠ ' : ''}${escapeHtml(d.reason)}</div>
          </td>
          <td class="muted-sm">${d.grammes.map(g => `${escapeHtml(g.onoma)} — ${fmtQty(g.posotita)} ${escapeHtml(g.monada)}`).join('<br>')}
            ${d.excluded.length ? `<br><i>Εξαιρούνται: ${d.excluded.map(x => `${escapeHtml(x.description)} (${escapeHtml(x.reason)})`).join(', ')}</i>` : ''}</td>
          <td class="muted-sm">${d.exported ? `<div style="color:var(--success);font-weight:600;" title="${escapeHtml(d.exported.file_name || '')}">✓ Εξήχθη ${escapeHtml(fmtDateTime(d.exported.exported_at))}${d.exported.count > 1 ? ` (${d.exported.count} φορές)` : ''}</div>${importBadge(d.exported)}` : ''}
            ${d.adeia ? `Άδεια ${escapeHtml(d.adeia)}, ${escapeHtml(d.ekdousa_archi)}` : ''}
            ${d.warnings.map(w => `<div>⚠ ${escapeHtml(w)}</div>`).join('')}</td>
          <td class="row-actions">
            ${d.source_pdf_filename ? `<button type="button" class="btn btn-outline btn-sm" data-xv-pdf="${escapeHtml(d.source_pdf_filename)}" title="Άνοιγμα PDF">📄</button>` : ''}
          </td>
        </tr>`).join('')}</tbody>
    </table></div>
    <div class="form-actions" style="margin-top:12px;">
      <button type="button" class="btn btn-primary" id="xv-export-btn"></button>
    </div>`;

  const boxes = [...container.querySelectorAll('.xv-cb:not([disabled])')];
  const btn = document.getElementById('xv-export-btn');
  const refreshBtn = () => {
    const checked = boxes.filter(b => b.checked);
    const again = checked.filter(b => xvDocs[parseInt(b.dataset.i, 10)].exported).length;
    btn.textContent = `Εξαγωγή JSON (${checked.length} παραστατικά${again ? `, ${again} ΞΑΝΑ` : ''})…`;
    btn.disabled = checked.length === 0;
    document.getElementById('xv-all').checked = checked.length === boxes.length;
  };
  refreshBtn();
  document.getElementById('xv-all').addEventListener('change', e => {
    boxes.forEach(b => { b.checked = e.target.checked; });
    refreshBtn();
  });
  boxes.forEach(b => b.addEventListener('change', refreshBtn));
  container.querySelectorAll('[data-xv-pdf]').forEach(b => b.addEventListener('click', async () => {
    const res = await window.api.openStoredFile(b.dataset.xvPdf);
    if (!res.ok) App.toast('Δεν ήταν δυνατό το άνοιγμα: ' + res.error, 'fail');
  }));

  btn.addEventListener('click', async () => {
    const tipos_overrides = {};
    container.querySelectorAll('.xv-tipos').forEach(sel => {
      const d = xvDocs[parseInt(sel.dataset.i, 10)];
      if (sel.value !== d.tipos) tipos_overrides[d.invoice_id] = sel.value;
    });
    const exclude_ids = container.querySelectorAll('.xv-cb').length
      ? [...container.querySelectorAll('.xv-cb')].filter(b => !b.checked).map(b => xvDocs[parseInt(b.dataset.i, 10)].invoice_id)
      : [];
    const again = [...container.querySelectorAll('.xv-cb:checked')].filter(b => xvDocs[parseInt(b.dataset.i, 10)].exported).length;
    if (again && !(await App.confirmAsync(
      `${again} από τα επιλεγμένα παραστατικά έχουν ΗΔΗ εξαχθεί για το expvault. Αν τα εισαγάγεις ` +
      `ξανά εκεί, θα καταχωρηθούν δύο φορές στο βιβλίο. Συνέχεια;`
    ))) return;
    const stamp = new Date().toISOString().slice(0, 10);
    const path = await window.api.saveJsonFile(`ekrhktika-expvault-${stamp}.json`);
    if (!path) return;
    const unlock = _lock(btn);
    try {
      const date_from = document.getElementById('xv-date-from').value || null;
      const date_to = document.getElementById('xv-date-to').value || null;
      const r = await pyCallStrict('expvault_export_write', { path, date_from, date_to, tipos_overrides, exclude_ids });
      App.toast(`Εξήχθησαν ${r.documents} παραστατικά (${r.eisagoges} εισαγωγές, ${r.epistrofes} επιστροφές, ${r.lines} γραμμές)`, 'ok');
      loadExpvaultPreview();
    } catch (e) {
      App.toast(e.message, 'fail');
    } finally {
      unlock();
    }
  });
}

document.getElementById('xv-preview-btn').addEventListener('click', loadExpvaultPreview);

// Φόρτωση αποδεικτικού εισαγωγής που βγάζει το ExpVault+ («🧾 Απόδειξη εισαγωγής») — σύγκριση ανά τιμολόγιο.
document.getElementById('xv-receipt-btn').addEventListener('click', async () => {
  const path = await window.api.openImportFile();   // διαλέγει JSON/CSV
  if (!path) return;
  const unlock = _lock(document.getElementById('xv-receipt-btn'));
  try {
    const r = await pyCallStrict('expvault_import_receipt_load', { file_path: path });
    const parts = [`✓ ${r.ok} εισήχθησαν`];
    if (r.mismatch) parts.push(`⚠ ${r.mismatch} με διαφορές`);
    if (r.pending) parts.push(`⏳ ${r.pending} εκκρεμούν`);
    if (r.unknown_exports.length) parts.push(`${r.unknown_exports.length} άγνωστα export_id`);
    if (r.unknown_documents) parts.push(`${r.unknown_documents} άγνωστα παραστατικά`);
    App.toast('Απόδειξη εισαγωγής: ' + parts.join(' · '), r.mismatch || r.unknown_exports.length ? 'warn' : 'ok');
    if (document.getElementById('xv-preview').innerHTML.trim()) loadExpvaultPreview();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});
