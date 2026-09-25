import { escapeHtml, normalizeGreek, normalizeMachineCode, attachAutocomplete } from '../../../js/utils.js';

function canonicalMachineName(name) {
  if (!name) return name;
  const machines = window.AppState.machines || [];
  if (machines.some(m => m.name === name)) return name;
  const norm = normalizeMachineCode(name);
  if (!norm) return name;
  const match = machines.find(m => normalizeMachineCode(m.name) === norm);
  return match ? match.name : name;
}

function resetAllocForm(card) {
  card.dataset.editingAllocId = '';
  card.querySelector('.pool-machine').value = '';
  card.querySelector('.pool-quantity').value = '';
  card.querySelector('.pool-date').value = '';
  card.querySelector('.pool-notes').value = '';
  card.querySelector('[data-allocate]').textContent = 'Κατανομή';
  card.querySelector('[data-cancel-alloc-edit]').style.display = 'none';
}

async function loadPools() {
  const container = document.getElementById('pools-list');
  const pools = await pyCall('list_open_bulk_pools') || [];

  if (!pools.length) {
    container.innerHTML = `<div class="empty-state"><div class="icon">🛢️</div><p>Κανένα ανοιχτό απόθεμα προς διαμοιρασμό.</p></div>`;
    return;
  }

  container.innerHTML = pools.map(p => {
    const mergeCandidates = pools.filter(o =>
      o.id !== p.id && (o.category || '') === (p.category || '') && (o.unit || '') === (p.unit || '')
    );
    return `
    <div class="pool-card" data-pool-id="${p.id}" data-category="${escapeHtml(p.category || '')}" data-unit="${escapeHtml(p.unit || '')}">
      <div class="pool-card-header">
        <b>${escapeHtml(p.description || p.category || '—')}</b>
        <span class="pool-remaining">${p.remaining_quantity} / ${p.total_quantity} ${escapeHtml(p.unit || '')}</span>
      </div>
      <div class="muted-sm">
        ${escapeHtml(p.doc_date || '—')} · ${escapeHtml(p.supplier_name || '—')}
        ${p.doc_number ? `· #${escapeHtml(p.doc_number)}` : ''}
      </div>

      ${p.allocations.length ? `
      <div class="pool-allocations">
        ${p.allocations.map(a => `
        <div class="pool-alloc-item" data-alloc-id="${a.id}">
          <span class="pool-alloc-machine">${escapeHtml(a.machine_name || '—')}</span>
          <span class="mono pool-alloc-quantity">${a.quantity} ${escapeHtml(p.unit || '')}</span>
          <span class="muted-sm pool-alloc-date">${escapeHtml(a.allocation_date || '')}</span>
          <span class="muted-sm pool-alloc-notes">${escapeHtml(a.notes || '')}</span>
          <button type="button" class="btn btn-outline btn-sm" data-edit-alloc="${a.id}" title="Επεξεργασία κατανομής">✏️</button>
          <button type="button" class="btn btn-outline btn-sm" data-delete-alloc="${a.id}" title="Διαγραφή κατανομής">🗑️</button>
        </div>
        `).join('')}
      </div>
      ` : ''}

      <div class="pool-alloc-row">
        <div><label>Μηχάνημα/Στόχος</label><input type="text" class="pool-machine"></div>
        <div><label>Ποσότητα</label><input type="number" step="0.001" class="pool-quantity"></div>
        <div><label>Ημερομηνία</label><input type="date" class="pool-date"></div>
        <div><label>Σημείωση</label><input type="text" class="pool-notes"></div>
        <button type="button" class="btn btn-primary btn-sm" data-allocate="${p.id}">Κατανομή</button>
        <button type="button" class="btn btn-outline btn-sm" data-cancel-alloc-edit style="display:none;">Άκυρο</button>
        <button type="button" class="btn btn-outline btn-sm" data-close-pool="${p.id}">Κλείσιμο</button>
        ${p.remaining_quantity == p.total_quantity ? `
        <button type="button" class="btn btn-outline btn-sm" data-undo-bulk="${p.id}" title="Η γραμμή σημάνθηκε bulk κατά λάθος — αφαίρεση της σήμανσης, όχι κλείσιμο">Δεν είναι bulk</button>
        ` : ''}
      </div>

      ${mergeCandidates.length ? `
      <div class="pool-merge-row">
        <select class="pool-merge-target">
          <option value="">— Μεταφορά υπολοίπου σε άλλο απόθεμα —</option>
          ${mergeCandidates.map(c => `
          <option value="${c.id}">${escapeHtml(c.description || c.category || '—')} (${c.remaining_quantity}/${c.total_quantity} ${escapeHtml(c.unit || '')})${c.doc_number ? ` · #${escapeHtml(c.doc_number)}` : ''}</option>
          `).join('')}
        </select>
        <button type="button" class="btn btn-outline btn-sm" data-merge-pool="${p.id}">Συγχώνευση</button>
      </div>
      ` : ''}
    </div>
  `;
  }).join('');

  attachAutocomplete(container, '.pool-machine', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });

  container.querySelectorAll('[data-allocate]').forEach(btn => btn.addEventListener('click', async () => {
    const card = btn.closest('.pool-card');
    const pool_id = parseInt(card.dataset.poolId, 10);
    const machine_name = canonicalMachineName(card.querySelector('.pool-machine').value) || null;
    const quantity = parseFloat(card.querySelector('.pool-quantity').value);
    const allocation_date = card.querySelector('.pool-date').value;
    const notes = card.querySelector('.pool-notes').value || null;
    if (!allocation_date) { App.toast('Όρισε ημερομηνία κατανομής', 'fail'); return; }
    const editingId = card.dataset.editingAllocId;
    try {
      if (editingId) {
        await pyCallStrict('update_allocation', {
          allocation_id: parseInt(editingId, 10), machine_name, quantity, allocation_date, notes
        });
        App.toast('Η κατανομή ενημερώθηκε', 'ok');
      } else {
        await pyCallStrict('add_allocation', { pool_id, machine_name, quantity, allocation_date, notes });
        App.toast('Η κατανομή καταχωρήθηκε', 'ok');
      }
      loadPools();
      window.reloadLookups();
    } catch (e) {
      App.toast(e.message, 'fail');
    }
  }));

  container.querySelectorAll('[data-edit-alloc]').forEach(btn => btn.addEventListener('click', () => {
    const card = btn.closest('.pool-card');
    const item = btn.closest('.pool-alloc-item');
    const allocId = btn.dataset.editAlloc;
    card.dataset.editingAllocId = allocId;
    card.querySelector('.pool-machine').value = item.querySelector('.pool-alloc-machine').textContent;
    card.querySelector('.pool-quantity').value = parseFloat(item.querySelector('.pool-alloc-quantity').textContent);
    card.querySelector('.pool-date').value = item.querySelector('.pool-alloc-date').textContent;
    card.querySelector('.pool-notes').value = item.querySelector('.pool-alloc-notes').textContent;
    card.querySelector('[data-allocate]').textContent = 'Ενημέρωση κατανομής';
    card.querySelector('[data-cancel-alloc-edit]').style.display = '';
    card.querySelector('.pool-machine').focus();
  }));

  container.querySelectorAll('[data-cancel-alloc-edit]').forEach(btn => btn.addEventListener('click', () => {
    resetAllocForm(btn.closest('.pool-card'));
  }));

  container.querySelectorAll('[data-delete-alloc]').forEach(btn => btn.addEventListener('click', () => {
    const allocation_id = parseInt(btn.dataset.deleteAlloc, 10);
    App.confirmDelete('Διαγραφή αυτής της κατανομής; Η ποσότητα επιστρέφει στο διαθέσιμο υπόλοιπο του αποθέματος.', async () => {
      try {
        await pyCallStrict('delete_allocation', { allocation_id });
        App.toast('Η κατανομή διαγράφηκε', 'ok');
        loadPools();
        window.reloadLookups();
      } catch (e) {
        App.toast(e.message, 'fail');
      }
    });
  }));

  container.querySelectorAll('[data-merge-pool]').forEach(btn => btn.addEventListener('click', () => {
    const card = btn.closest('.pool-card');
    const merge_id = parseInt(card.dataset.poolId, 10);
    const select = card.querySelector('.pool-merge-target');
    const keep_id = parseInt(select.value, 10);
    if (!keep_id) { App.toast('Διάλεξε απόθεμα προορισμού', 'fail'); return; }
    const targetLabel = select.options[select.selectedIndex].textContent;
    App.confirmDelete(
      `Μεταφορά όλου του υπολοίπου (και του ιστορικού κατανομών) αυτού του αποθέματος μέσα στο "${targetLabel}"; Αυτό το απόθεμα θα κλείσει.`,
      async () => {
        try {
          await pyCallStrict('merge_bulk_pools', { keep_id, merge_id });
          App.toast('Τα αποθέματα συγχωνεύτηκαν', 'ok');
          loadPools();
        } catch (e) {
          App.toast(e.message, 'fail');
        }
      }
    );
  }));

  container.querySelectorAll('[data-close-pool]').forEach(btn => btn.addEventListener('click', () => {
    document.getElementById('close-pool-id').value = btn.dataset.closePool;
    document.getElementById('close-pool-note').value = '';
    document.getElementById('close-pool-modal').classList.add('open');
  }));
  container.querySelectorAll('[data-undo-bulk]').forEach(btn => btn.addEventListener('click', () => {
    const pool_id = parseInt(btn.dataset.undoBulk, 10);
    App.confirmDelete('Η γραμμή δεν είναι bulk — αφαίρεση της σήμανσης; Η γραμμή τιμολογίου παραμένει, απλά δεν θα εμφανίζεται πια εδώ.', async () => {
      try {
        await pyCallStrict('delete_bulk_pool', { pool_id });
        App.toast('Η σήμανση bulk αφαιρέθηκε', 'ok');
        loadPools();
      } catch (e) {
        App.toast(e.message, 'fail');
      }
    });
  }));
}

document.getElementById('close-pool-cancel-btn').addEventListener('click', () => {
  document.getElementById('close-pool-modal').classList.remove('open');
});
document.getElementById('close-pool-ok-btn').addEventListener('click', async () => {
  const pool_id = parseInt(document.getElementById('close-pool-id').value, 10);
  const note = document.getElementById('close-pool-note').value || null;
  try {
    await pyCallStrict('close_bulk_pool', { pool_id, note });
    document.getElementById('close-pool-modal').classList.remove('open');
    App.toast('Το απόθεμα έκλεισε', 'ok');
    loadPools();
  } catch (e) {
    App.toast(e.message, 'fail');
  }
});

loadPools();
