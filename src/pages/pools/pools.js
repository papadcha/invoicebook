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

async function loadPools() {
  const container = document.getElementById('pools-list');
  const pools = await pyCall('list_open_bulk_pools') || [];

  if (!pools.length) {
    container.innerHTML = `<div class="empty-state"><div class="icon">🛢️</div><p>Κανένα ανοιχτό απόθεμα προς διαμοιρασμό.</p></div>`;
    return;
  }

  container.innerHTML = pools.map(p => `
    <div class="pool-card" data-pool-id="${p.id}">
      <div class="pool-card-header">
        <b>${escapeHtml(p.description || p.category || '—')}</b>
        <span class="pool-remaining">${p.remaining_quantity} / ${p.total_quantity} ${escapeHtml(p.unit || '')}</span>
      </div>
      <div class="muted-sm">
        ${escapeHtml(p.doc_date || '—')} · ${escapeHtml(p.supplier_name || '—')}
        ${p.doc_number ? `· #${escapeHtml(p.doc_number)}` : ''}
      </div>
      <div class="pool-alloc-row">
        <div><label>Μηχάνημα/Στόχος</label><input type="text" class="pool-machine"></div>
        <div><label>Ποσότητα</label><input type="number" step="0.001" class="pool-quantity"></div>
        <div><label>Ημερομηνία</label><input type="date" class="pool-date"></div>
        <div><label>Σημείωση</label><input type="text" class="pool-notes"></div>
        <button type="button" class="btn btn-primary btn-sm" data-allocate="${p.id}">Κατανομή</button>
        <button type="button" class="btn btn-outline btn-sm" data-close-pool="${p.id}">Κλείσιμο</button>
        ${p.remaining_quantity == p.total_quantity ? `
        <button type="button" class="btn btn-outline btn-sm" data-undo-bulk="${p.id}" title="Η γραμμή σημάνθηκε bulk κατά λάθος — αφαίρεση της σήμανσης, όχι κλείσιμο">Δεν είναι bulk</button>
        ` : ''}
      </div>
    </div>
  `).join('');

  attachAutocomplete(container, '.pool-machine', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });

  container.querySelectorAll('[data-allocate]').forEach(btn => btn.addEventListener('click', async () => {
    const card = btn.closest('.pool-card');
    const pool_id = parseInt(btn.dataset.allocate, 10);
    const machine_name = canonicalMachineName(card.querySelector('.pool-machine').value) || null;
    const quantity = parseFloat(card.querySelector('.pool-quantity').value);
    const allocation_date = card.querySelector('.pool-date').value;
    const notes = card.querySelector('.pool-notes').value || null;
    if (!allocation_date) { App.toast('Όρισε ημερομηνία κατανομής', 'fail'); return; }
    try {
      await pyCallStrict('add_allocation', { pool_id, machine_name, quantity, allocation_date, notes });
      App.toast('Η κατανομή καταχωρήθηκε', 'ok');
      loadPools();
      window.reloadLookups();
    } catch (e) {
      App.toast(e.message, 'fail');
    }
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
