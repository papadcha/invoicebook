import {
  escapeHtml, fmtMoney, fmtDate, fmtQty, _lock,
  normalizeGreek, normalizeMachineCode, normalizeCategory, attachAutocomplete,
} from '../../../js/utils.js';

const CURRENT_PDF_SENTINEL = '__CURRENT_PDF__'; // πρέπει να ταιριάζει με database.py's σταθερά

function canonicalMachineName(name) {
  if (!name) return name;
  const machines = window.AppState.machines || [];
  if (machines.some(m => m.name === name)) return name;
  const norm = normalizeMachineCode(name);
  if (!norm) return name;
  const match = machines.find(m => normalizeMachineCode(m.name) === norm);
  return match ? match.name : name;
}

// ── AI PROMPT ────────────────────────────────────────────────────────────────
// Ένα μόνο, γενικό prompt — ζητάει category/machine_name/efk_eligible/bulk ανά
// γραμμή, ώστε η κατηγοριοποίηση να έρχεται έτοιμη από το AI (ο χειριστής τη
// διορθώνει παρακάτω στην προεπισκόπηση αν χρειαστεί).
const IMPORT_PROMPT = `Ανάλυσε ΟΛΕΣ τις φωτογραφίες τιμολογίων/παραστατικών που σου στέλνω σε αυτό το μήνυμα — μπορεί να είναι μία ή πολλές. Απάντησε ΜΟΝΟ με ένα markdown code block τύπου json (ξεκινώντας με τρεις ανάστροφες παύλες + json, τελειώνοντας με τρεις ανάστροφες παύλες) που περιέχει ΕΝΑ JSON array [...] με ΕΝΑ αντικείμενο για ΚΑΘΕ φωτογραφία/τιμολόγιο (ποτέ λιγότερα αντικείμενα από φωτογραφίες), με την ίδια σειρά, στη μορφή παρακάτω. Μην γράψεις καθόλου άλλο κείμενο πριν ή μετά το code block:

[
  {
    "supplier_name": "όνομα προμηθευτή/εταιρείας",
    "supplier_vat": "ΑΦΜ προμηθευτή, αν αναγράφεται",
    "doc_type": "τύπος παραστατικού (π.χ. Τιμολόγιο, Δελτίο Αποστολής)",
    "doc_number": "αριθμός παραστατικού",
    "doc_date": "ΕΕΕΕ-ΜΜ-ΗΗ",
    "doc_time": "ΩΩ:ΛΛ, αν αναγράφεται",
    "customer_name": "όνομα πελάτη, αν αναγράφεται",
    "customer_vat": "ΑΦΜ πελάτη, αν αναγράφεται",
    "customer_doy": "ΔΟΥ πελάτη, αν αναγράφεται",
    "customer_address": "διεύθυνση πελάτη, αν αναγράφεται",
    "customer_phone": "τηλέφωνο πελάτη, αν αναγράφεται",
    "net_amount": αριθμός,
    "vat_amount": αριθμός,
    "total_amount": αριθμός,
    "payment_method": "τρόπος πληρωμής, αν αναγράφεται",
    "notes": "παρατηρήσεις, αν υπάρχουν. ΕΙΔΙΚΑ όταν το έγγραφο αφορά εκρηκτικά (οποιαδήποτε γραμμή θα έχει category='Εκρηκτικά' παρακάτω): ψάξε ρητά για άδεια μεταφοράς/κατοχής εκρηκτικών — τυπωμένα πεδία 'ΑΡΙΘ. ΑΔΕΙΑΣ'/'ΕΚΔΟΥΣΑ ΑΡΧΗ' ή χειρόγραφο στο κάτω μέρος τύπου 'ΑΔΕΙΑ 4658' + 'Α.Δ. ΧΑΛΚΙΔΙΚΗΣ' (Αστυνομική Διεύθυνση) — και αν τα βρεις πρόσθεσε στην αρχή του notes ακριβώς τη γραμμή 'Άδεια: <αριθμός>, Εκδούσα αρχή: <αρχή>' (π.χ. 'Άδεια: 40098, Εκδούσα αρχή: Α.Δ. Χαλκιδικής'), πριν από οποιαδήποτε άλλη παρατήρηση· το invoicebook δεν έχει ξεχωριστά πεδία γι' αυτό, μπαίνει εδώ ως ελεύθερο κείμενο ώστε να διαβάζεται αργότερα. Αν δεν βρεις τέτοια ένδειξη, μην το μαντέψεις.",
    "items": [
      {
        "code": "κωδικός είδους, αν υπάρχει",
        "description": "περιγραφή είδους/εργασίας",
        "unit": "μονάδα μέτρησης — ΜΟΝΟ μία από: L (λίτρα), kg (κιλά), ΤΕΜ (τεμάχια), m (μέτρα). Ποτέ ολογράφως (όχι 'Λίτρο', 'Κιλά', 'PIECES'). Για γραμμές υπηρεσίας/εργασίας (ΤΠΥ) άφησέ το κενό/null — το doc_type ήδη δηλώνει ότι είναι υπηρεσία, δεν χρειάζεται ψεύτικη μονάδα. ΠΡΟΣΟΧΗ σε τιμολόγια όπου η στήλη Μ/Μ δείχνει τύπο ΣΥΣΚΕΥΑΣΙΑΣ αντί για πραγματική μονάδα (π.χ. ΚΑΔΟΣ, ΚΑΔΟΣ ΠΛΑΣΤ, ΒΑΡΕΛΙ, ΧΑΡΤ/ΤΙΟ, ΔΟΧΕΙΟ, ΚΙΒΩΤΙΟ) — μην την αντιγράψεις κυριολεκτικά σαν unit· ψάξε το μέγεθος συσκευασίας μέσα στην περιγραφή/κωδικό είδους (π.χ. '...1X18L' = 18 λίτρα ανά κάδο, '...1X204L' = 204 λίτρα ανά βαρέλι, '...4X4KG' = 16 κιλά ανά κιβώτιο) και βάλε unit='L' ή 'kg' ανάλογα — βλ. οδηγία στο quantity/unit_price παρακάτω για τη μετατροπή",
        "quantity": "αριθμός — αν εφαρμόστηκε η μετατροπή συσκευασίας→L/kg παραπάνω, γράψε την ΠΡΑΓΜΑΤΙΚΗ συνολική ποσότητα σε λίτρα/κιλά (πλήθος συσκευασιών × μέγεθος συσκευασίας), όχι το τυπωμένο πλήθος συσκευασιών",
        "unit_price": "αριθμός — τιμή ΑΝΑ ΜΟΝΑΔΑ (ανά λίτρο/κιλό/τεμάχιο/μέτρο), ώστε quantity × unit_price να βγάζει την προ έκπτωσης αξία της γραμμής· αν έγινε μετατροπή συσκευασίας, διαίρεσε την τυπωμένη τιμή ανά συσκευασία με το μέγεθος συσκευασίας",
        "value": "αριθμός — ΠΡΟΣΟΧΗ, συχνό λάθος: σε τιμολόγια με στήλες 'Έκπτωση %' / 'Έκπτωση Αξία' / 'Καθ. Αξία' δίπλα-δίπλα, ΠΟΤΕ μην πάρεις τη στήλη 'Έκπτωση Αξία' (=το ΠΟΣΟ της έκπτωσης που αφαιρείται) ως value — αυτή είναι μικρότερη και ΛΑΘΟΣ. Το value είναι πάντα η στήλη 'Καθ. Αξία' (η ΤΕΛΙΚΗ αξία της γραμμής ΜΕΤΑ την έκπτωση, η μεγαλύτερη από τις δύο). Αν η γραμμή έχει από κάτω μια μικρή υπο-γραμμή 'ΠΕΡΙΒ. ΕΙΣΦΟΡΑ ΒΑΣΕΙ ΤΟΥ ΝΟΜΟΥ 2939/01' με ένα μικρό ποσό, μην το προσθέσεις σε αυτό το value (δεν είναι δικό της item, απλά μια σημείωση κάτω από την προηγούμενη γραμμή) — μην μπερδευτείς από τη θέση της και πάρεις λάθος αριθμό για τη διπλανή γραμμή. ΑΛΛΑ μην την πετάξεις: άθροισε ΟΛΑ τα ποσά 'ΠΕΡΙΒ. ΕΙΣΦΟΡΑ ΒΑΣΕΙ ΤΟΥ ΝΟΜΟΥ 2939/01' όλου του τιμολογίου (συνήθως ταιριάζει με το πεδίο 'ΕΞΟΔΑ' στο συνολικό κουτί κάτω) και πρόσθεσε ΜΙΑ επιπλέον γραμμή στο τέλος του items array με αυτό το άθροισμα ως value, description 'Περιβαλλοντική εισφορά', ίδιο vat_pct με τις υπόλοιπες γραμμές — έχει ξαναγίνει λάθος 70+ φορές να μένει έξω τελείως από την καταχώρηση.",
        "vat_pct": αριθμός,
        "category": "κατηγορία είδους — π.χ. Καύσιμα, Λιπαντικά, Ανταλλακτικά, Εργαλεία, Service/Εργασία, Αναλώσιμα/Γενικά",
        "machine_name": "μηχάνημα/όχημα/εγκατάσταση που αφορά — έλεγξε και χειρόγραφες σημειώσεις/σκαλίσματα στο έγγραφο, όχι μόνο τυπωμένα πεδία· δεκτός και γενικός προορισμός όπως «ΕΓΚΑΤΑΣΤΑΣΕΙΣ»/«ΓΡΑΦΕΙΟ»/«ΣΥΓΚΡΟΤΗΜΑ», όχι μόνο συγκεκριμένο μηχάνημα. Αν δεν βρεις καμία τέτοια ένδειξη, άφησέ το null — ΠΟΤΕ μην βάλεις εδώ τη λέξη/φράση από το description της ίδιας γραμμής, το category, ή το όνομα του προμηθευτή/πελάτη σαν να ήταν μηχάνημα (π.χ. αν η περιγραφή είναι 'ΡΟΥΛΕΜΑΝ SKF' το machine_name ΔΕΝ είναι 'ρουλεμάν'· αν δεν βλέπεις πραγματική ένδειξη μηχανήματος, null, όχι μαντεψιά από γειτονικά πεδία). ΠΡΟΣΟΧΗ, 4 επιπλέον συγκεκριμένες παγίδες που έχουν ξαναγίνει λάθος επανειλημμένα σε πραγματικά τιμολόγια: (1) Σε τιμολόγια φίλτρων/ανταλλακτικών η περιγραφή συχνά αναφέρει με ΠΟΙΑ μηχανήματα/μάρκες είναι ΣΥΜΒΑΤΟ το ανταλλακτικό γενικά (π.χ. 'Φ.ΑΕΡΟΣ ALLIS M.F J.DEERE') — αυτό ΔΕΝ σημαίνει ότι ΑΥΤΟ το μηχάνημα παρήγγειλε το φίλτρο σήμερα, είναι το γενικό fitment του part number· μην το βάλεις σαν machine_name, ψάξε αποκλειστικά το χειρόγραφο σημείωμα δίπλα στη γραμμή. (2) Η στήλη ΚΩΔΙΚΟΣ/κωδικός είδους (π.χ. 'MD260K') είναι κωδικός ΠΡΟΪΟΝΤΟΣ, ποτέ machine_name. (3) Τυπωμένα πεδία όπως 'ΟΧΗΜΑ', 'ΑΡΙΘΜΟΣ ΟΧΗΜΑΤΟΣ', 'ΜΕΤΑΦΟΡΙΚΟ ΜΕΣΟ', 'ΑΡ. ΑΥΤΟΚΙΝΗΤΟΥ' δείχνουν συνήθως το όχημα ΠΑΡΑΔΟΣΗΣ του ΠΡΟΜΗΘΕΥΤΗ, όχι το μηχάνημα-στόχο της εταιρείας μας — μην τα χρησιμοποιήσεις ως machine_name παρά μόνο αν υπάρχει ξεχωριστό χειρόγραφο σημείωμα που το επιβεβαιώνει ρητά ως πραγματικό μηχάνημα. (4) Σφραγίδες/λογότυπα/watermarks πάνω στη σελίδα δεν είναι machine_name.",
        "efk_eligible": true ή false (μόνο για καύσιμο κίνησης με δικαίωμα επιστροφής ΕΦΚ),
        "bulk": true ή false (true αν είναι χύδην/μαζική παράδοση χωρίς άμεσο συγκεκριμένο μηχάνημα, π.χ. γέμισμα δεξαμενής)
      }
    ]
  }
]`;

document.getElementById('copy-prompt-btn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  try {
    await navigator.clipboard.writeText(IMPORT_PROMPT);
    App.toast('✅ Το prompt αντιγράφηκε — επικόλλησέ το στο Claude/Gemini μαζί με τις φωτογραφίες', 'ok');
    const original = btn.textContent;
    btn.textContent = '✅ Αντιγράφηκε';
    setTimeout(() => { btn.textContent = original; }, 1500);
  } catch (e) {
    App.toast('Δεν ήταν δυνατή η αντιγραφή: ' + e.message, 'fail');
  }
});

// Datalist κατηγοριών (χρησιμοποιείται από τα inputs της προεπισκόπησης).
document.getElementById('category-options').innerHTML =
  (window.AppState.categories || []).map(c => `<option value="${escapeHtml(c)}"></option>`).join('');

// ── ΕΠΙΛΟΓΗ ΑΡΧΕΙΟΥ + ΠΡΟΕΠΙΣΚΟΠΗΣΗ ──────────────────────────────────────────
let pickedFilePath = null;
let previewInvoices = null; // [{ header fields..., items: [...] }]

document.getElementById('pick-file-btn').addEventListener('click', async () => {
  const filePath = await window.api.openImportFile();
  if (!filePath) return;
  pickedFilePath = filePath;
  document.getElementById('picked-file-name').textContent = filePath.split(/[\\/]/).pop();

  const unlock = _lock(document.getElementById('pick-file-btn'));
  try {
    const rows = await pyCallStrict('parse_import_file', { file_path: pickedFilePath });
    previewInvoices = rows.map(r => ({ ...r, items: (r.items || []).map(it => ({ ...it })) }));
    renderPreview();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

function qtyLabel(it) {
  if (it.quantity === null || it.quantity === undefined || it.quantity === '') return '—';
  return `${fmtQty(it.quantity)}${it.unit ? ' ' + it.unit : ''}`;
}

function renderPreview() {
  const card = document.getElementById('preview-card');
  if (!previewInvoices || !previewInvoices.length) { card.style.display = 'none'; return; }
  card.style.display = '';

  const names = previewInvoices.map(inv => inv.supplier_name).filter(Boolean);
  document.getElementById('preview-supplier').textContent = names.join(', ') || '—';
  const dates = [...new Set(previewInvoices.map(inv => inv.doc_date).filter(Boolean))];
  document.getElementById('preview-date').textContent = dates.map(fmtDate).join(', ') || '—';

  const body = document.getElementById('preview-body');
  body.innerHTML = previewInvoices.map((inv, invIdx) => {
    const headerRow = previewInvoices.length > 1
      ? `<tr><td colspan="6" style="background:var(--bg); font-weight:600; font-size:12px; color:var(--navy2);">${escapeHtml(inv.supplier_name || '—')} — ${escapeHtml(fmtDate(inv.doc_date) || '—')} (${escapeHtml(inv.doc_number || '—')})</td></tr>`
      : '';
    const itemRows = inv.items.map((it, itIdx) => `
      <tr data-inv="${invIdx}" data-it="${itIdx}">
        <td>${escapeHtml(it.description || '')}</td>
        <td class="mono">${qtyLabel(it)}</td>
        <td><input class="it-category" type="text" list="category-options" value="${escapeHtml(it.category || '')}" data-f="category" style="width:150px;"></td>
        <td><input class="it-machine" type="text" value="${escapeHtml(it.machine_name || '')}" data-f="machine_name" style="width:150px;"></td>
        <td style="text-align:center;"><input type="checkbox" data-f="efk_eligible" ${it.efk_eligible ? 'checked' : ''}></td>
        <td style="text-align:center;"><input type="checkbox" data-f="bulk" ${it.bulk ? 'checked' : ''}></td>
      </tr>
    `).join('');
    return headerRow + itemRows;
  }).join('');

  body.querySelectorAll('input[data-f]').forEach(input => {
    input.addEventListener('input', () => {
      const tr = input.closest('tr');
      const inv = previewInvoices[parseInt(tr.dataset.inv, 10)];
      const it = inv.items[parseInt(tr.dataset.it, 10)];
      const field = input.dataset.f;
      it[field] = input.type === 'checkbox' ? input.checked : input.value;
    });
  });

  attachAutocomplete(body, '.it-category', () => window.AppState.categories || [], { normalize: normalizeGreek });
  attachAutocomplete(body, '.it-machine', () => (window.AppState.machines || []).map(m => m.name), { normalize: normalizeGreek });
}

document.getElementById('apply-first-btn').addEventListener('click', () => {
  if (!previewInvoices) return;
  previewInvoices.forEach(inv => {
    if (!inv.items.length) return;
    const { category, machine_name, efk_eligible, bulk } = inv.items[0];
    inv.items.forEach((it, i) => { if (i > 0) Object.assign(it, { category, machine_name, efk_eligible, bulk }); });
  });
  renderPreview();
});

document.getElementById('discard-preview-btn').addEventListener('click', () => {
  previewInvoices = null;
  pickedFilePath = null;
  document.getElementById('picked-file-name').textContent = 'Κανένα αρχείο';
  renderPreview();
});

document.getElementById('stage-rows-btn').addEventListener('click', async () => {
  if (!previewInvoices || !previewInvoices.length) return;
  const batch_label = document.getElementById('batch-label').value.trim() || null;
  const unlock = _lock(document.getElementById('stage-rows-btn'));
  try {
    const rows = previewInvoices.map(inv => ({
      ...inv,
      items: inv.items.map(it => ({ ...it, category: normalizeCategory(it.category), machine_name: canonicalMachineName(it.machine_name) })),
    }));
    const ids = await pyCallStrict('stage_rows', { rows, batch_label });
    App.toast(`Εισήχθησαν ${ids.length} γραμμές για επιβεβαίωση`, 'ok');
    previewInvoices = null;
    pickedFilePath = null;
    document.getElementById('picked-file-name').textContent = 'Κανένα αρχείο';
    renderPreview();
    loadStaging();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

// ── ΣΕ ΑΝΑΜΟΝΗ ΕΠΙΒΕΒΑΙΩΣΗΣ ──────────────────────────────────────────────────
let stagingRowsById = {};

function isPureDuplicateOfInvoice(existingItems, newItems) {
  if (!newItems.length) return false;
  const existingKeys = new Set(existingItems.map(mergeItemDupKey));
  return newItems.every(it => existingKeys.has(mergeItemDupKey(it)));
}

async function loadStaging() {
  const body = document.getElementById('staging-body');
  const mergeBtn = document.getElementById('staging-merge-btn');
  const rows = await pyCall('get_staging_batch', { status: 'pending' }) || [];
  stagingRowsById = Object.fromEntries(rows.map(r => [r.id, r]));
  mergeBtn.disabled = true;

  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7"><div class="empty-state"><div class="icon">📂</div><p>Δεν υπάρχουν γραμμές σε αναμονή.</p></div></td></tr>`;
    return;
  }
  body.innerHTML = rows.map(r => {
    const d = r.data;
    return `
      <tr data-id="${r.id}">
        <td><input type="checkbox" data-staging-select="${r.id}"></td>
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

  function updateMergeBtnState() {
    const checked = body.querySelectorAll('[data-staging-select]:checked').length;
    mergeBtn.disabled = checked < 2;
  }
  body.querySelectorAll('[data-staging-select]').forEach(cb => cb.addEventListener('change', updateMergeBtnState));

  body.querySelectorAll('[data-confirm]').forEach(btn => btn.addEventListener('click', async () => {
    const stagingId = parseInt(btn.dataset.confirm, 10);
    const row = stagingRowsById[stagingId];
    const unlock = _lock(btn);
    try {
      const dup = await pyCallStrict('find_duplicate_invoice', { header: row.data });
      if (dup) {
        const invoice = await pyCall('get_invoice', { id: dup.id });
        if (invoice && isPureDuplicateOfInvoice(invoice.items || [], row.data.items || [])) {
          App.confirmDelete(
            `Αυτή η γραμμή φαίνεται ΑΚΡΙΒΕΣ διπλότυπο του ήδη καταχωρημένου τιμολογίου #${invoice.id} ` +
            `(${dup.doc_number || '—'}, ${dup.doc_date}, σύνολο ${dup.total_amount ?? '—'}€) — όλα τα items της υπάρχουν ήδη εκεί, ` +
            `δεν φέρνει τίποτα καινούργιο. Απόρριψη ως διπλότυπο;`,
            async () => {
              try {
                await pyCallStrict('reject_staging_row', { id: stagingId });
                App.toast('Απορρίφθηκε ως διπλότυπο', 'ok');
                loadStaging();
              } catch (e) {
                App.toast(e.message, 'fail');
              }
            },
            () => openMergeDialog({ invoice, stagingRows: [row] })
          );
          unlock();
          return;
        }
        openMergeDialog({ invoice, stagingRows: [row] });
        unlock();
        return;
      }
      // Layer 1: ίδιο ΑΚΡΙΒΩΣ αρχείο PDF με ήδη καταχωρημένο τιμολόγιο -- πιάνει
      // διπλοκαταχωρήσεις που ο παραπάνω έλεγχος χάνει όταν ο αριθμός/η ημερομηνία
      // διαβάστηκαν διαφορετικά (π.χ. «236» / «Κ2 236», 2026-09-23).
      const samePdf = await pyCallStrict('find_invoices_with_same_pdf', { paths: row.data.source_pdf_path });
      if (samePdf.length) {
        const invoices = [...new Map(samePdf.map(i => [i.id, i])).values()]
          .map(i => `#${i.id} (${i.doc_number || '—'}, ${i.doc_date}, ${i.supplier_name || '—'})`).join(', ');
        const proceed = await App.confirmAsync(
          `Το PDF αυτής της γραμμής είναι ΙΔΙΟ ακριβώς αρχείο με το PDF του ήδη καταχωρημένου ` +
          `τιμολογίου ${invoices} — πιθανή διπλοκαταχώρηση (ο αριθμός ή η ημερομηνία ίσως ` +
          `διαβάστηκαν διαφορετικά). Καταχώρηση παρ' όλα αυτά;`
        );
        if (!proceed) { unlock(); return; }
      }
      // Το confirm_staging_row επισυνάπτει ήδη το PDF (source_pdf_path) στο backend --
      // ένα δεύτερο attach_pdf εδώ έβρισκε το αρχείο ήδη μετακινημένο και έβγαζε ψευδές
      // «δεν επισυνάφθηκε».
      await pyCallStrict('confirm_staging_row', { id: stagingId });
      App.toast('Καταχωρήθηκε ως τιμολόγιο', 'ok');
      window.reloadLookups();
      loadStaging();
    } catch (e) {
      App.toast(e.message, 'fail');
      unlock();
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

document.getElementById('staging-merge-btn').addEventListener('click', () => {
  const checkedIds = Array.from(document.querySelectorAll('#staging-body [data-staging-select]:checked'))
    .map(cb => parseInt(cb.dataset.stagingSelect, 10));
  const stagingRows = checkedIds.map(id => stagingRowsById[id]).filter(Boolean);
  if (stagingRows.length < 2) return;
  openMergeDialog({ invoice: null, stagingRows });
});

// ── ΕΝΩΣΗ ΣΕΛΙΔΩΝ ΠΑΡΑΣΤΑΤΙΚΟΥ ────────────────────────────────────────────────
// Πάντα "πλήρης αντικατάσταση" — τα τελικά επιλεγμένα items στέλνονται χωρίς
// 'id' στο merge_documents (βλ. database.py), άρα δεν χρειάζεται να ξέρουμε αν
// οι πηγές έχουν συμπληρωματικά ή επικαλυπτόμενα items· ο χειριστής απλά
// αποεπιλέγει τις διπλές γραμμές με το μάτι, καθοδηγούμενος από το ζωντανό
// άθροισμα έναντι του net_amount.
let mergePdfOrder = [];
let mergeTargetInvoiceId = null;
let mergeStagingIds = [];

function mergeItemDupKey(it) {
  const code = (it.code || '').trim().toUpperCase();
  if (code) return 'code:' + code;
  const desc = (it.description || '').trim().toLowerCase().replace(/\s+/g, ' ');
  const value = Math.round((it.value ?? 0) * 100);
  return `desc:${desc}|${value}`;
}

function mergeItemRowHtml(sourceLabel, it, { checked = true, duplicate = false } = {}) {
  const rowStyle = duplicate ? ' style="background:#fff3cd;"' : '';
  const dupBadge = duplicate ? ' ⚠' : '';
  return `
    <tr data-item-row${rowStyle} ${duplicate ? 'title="Πιθανό διπλότυπο -- ίδιος κωδικός/περιγραφή με άλλη γραμμή, βρέθηκε σε παραπάνω από μία πηγή"' : ''}>
      <td style="text-align:center;"><input type="checkbox" data-f="selected" ${checked ? 'checked' : ''}></td>
      <td class="muted-sm">${escapeHtml(sourceLabel)}${dupBadge}</td>
      <td><input type="text" data-f="description" value="${escapeHtml(it.description || '')}"></td>
      <td><input type="text" data-f="category" value="${escapeHtml(it.category || '')}"></td>
      <td><input type="number" step="0.001" data-f="quantity" value="${it.quantity ?? ''}" style="width:80px;"></td>
      <td><input type="text" data-f="unit" value="${escapeHtml(it.unit || '')}" style="width:56px;"></td>
      <td><input type="number" step="0.001" data-f="unit_price" value="${it.unit_price ?? ''}" style="width:90px;"></td>
      <td><input type="number" step="0.01" data-f="value" value="${it.value ?? ''}" style="width:90px;"></td>
      <td><input type="number" step="0.1" data-f="vat_pct" value="${it.vat_pct ?? ''}" style="width:64px;"></td>
      <td><input type="text" data-f="machine_name" value="${escapeHtml(it.machine_name || '')}"></td>
      <td style="text-align:center;"><input type="checkbox" data-f="efk_eligible" ${it.efk_eligible ? 'checked' : ''} style="width:auto;"></td>
    </tr>
  `;
}

function renderMergePdfOrder() {
  const el = document.getElementById('merge-pdf-order-list');
  if (!mergePdfOrder.length) {
    el.innerHTML = '<p class="muted-sm">Καμία πηγή με συνδεδεμένο PDF.</p>';
    return;
  }
  el.innerHTML = mergePdfOrder.map((entry, i) => `
    <div style="display:flex; align-items:center; gap:8px; padding:4px 0;">
      <span class="mono muted-sm" style="width:20px;">${i + 1}.</span>
      <span style="flex:1;">${escapeHtml(entry.label)}</span>
      <button type="button" class="btn btn-outline btn-sm" data-pdf-open="${i}">👁 Άνοιγμα</button>
      <button type="button" class="btn btn-outline btn-sm" data-pdf-up="${i}" ${i === 0 ? 'disabled' : ''}>▲</button>
      <button type="button" class="btn btn-outline btn-sm" data-pdf-down="${i}" ${i === mergePdfOrder.length - 1 ? 'disabled' : ''}>▼</button>
    </div>
  `).join('');
  el.querySelectorAll('[data-pdf-open]').forEach(btn => btn.addEventListener('click', async () => {
    const entry = mergePdfOrder[parseInt(btn.dataset.pdfOpen, 10)];
    const res = await entry.open();
    if (!res.ok) App.toast('Δεν ήταν δυνατό το άνοιγμα: ' + res.error, 'fail');
  }));
  el.querySelectorAll('[data-pdf-up]').forEach(btn => btn.addEventListener('click', () => {
    const i = parseInt(btn.dataset.pdfUp, 10);
    [mergePdfOrder[i - 1], mergePdfOrder[i]] = [mergePdfOrder[i], mergePdfOrder[i - 1]];
    renderMergePdfOrder();
  }));
  el.querySelectorAll('[data-pdf-down]').forEach(btn => btn.addEventListener('click', () => {
    const i = parseInt(btn.dataset.pdfDown, 10);
    [mergePdfOrder[i + 1], mergePdfOrder[i]] = [mergePdfOrder[i], mergePdfOrder[i + 1]];
    renderMergePdfOrder();
  }));
}

function updateMergeSumStatus() {
  const rows = Array.from(document.querySelectorAll('#merge-items-body tr[data-item-row]'));
  let sum = 0;
  rows.forEach(tr => {
    if (!tr.querySelector('[data-f="selected"]').checked) return;
    sum += parseFloat(tr.querySelector('[data-f="value"]').value) || 0;
  });
  const net = parseFloat(document.getElementById('merge-net-amount').value);
  const status = document.getElementById('merge-sum-status');
  const sumFmt = fmtQty(sum);
  if (!isNaN(net) && Math.abs(sum - net) < 0.02) {
    status.textContent = `✅ Σύνολο επιλεγμένων: ${sumFmt}€ (ταιριάζει με την Καθ. Αξία)`;
    status.style.color = 'var(--success)';
  } else {
    status.textContent = `⚠ Σύνολο επιλεγμένων: ${sumFmt}€` + (isNaN(net) ? '' : ` — Καθ. Αξία: ${fmtQty(net)}€`);
    status.style.color = 'var(--danger)';
  }
}

function recalcMergeHeaderFromItems() {
  const rows = Array.from(document.querySelectorAll('#merge-items-body tr[data-item-row]'));
  let net = 0, vat = 0;
  rows.forEach(tr => {
    if (!tr.querySelector('[data-f="selected"]').checked) return;
    const value = parseFloat(tr.querySelector('[data-f="value"]').value) || 0;
    const vatPct = parseFloat(tr.querySelector('[data-f="vat_pct"]').value) || 0;
    net += value;
    vat += value * vatPct / 100;
  });
  document.getElementById('merge-net-amount').value = net.toFixed(2);
  document.getElementById('merge-vat-amount').value = vat.toFixed(2);
  document.getElementById('merge-total-amount').value = (net + vat).toFixed(2);
}

function openMergeDialog({ invoice, stagingRows }) {
  mergeTargetInvoiceId = invoice ? invoice.id : null;
  mergeStagingIds = stagingRows.map(r => r.id);

  const suppliers = window.AppState.suppliers || [];
  const headerSource = invoice
    ? {
        supplier_name: (suppliers.find(s => s.id === invoice.supplier_id) || {}).name || '',
        supplier_vat: (suppliers.find(s => s.id === invoice.supplier_id) || {}).vat_number || '',
        doc_type: invoice.doc_type, doc_number: invoice.doc_number, doc_date: invoice.doc_date,
        doc_time: invoice.doc_time, net_amount: invoice.net_amount, vat_amount: invoice.vat_amount,
        total_amount: invoice.total_amount,
      }
    : stagingRows[0].data;
  document.getElementById('merge-supplier-name').value = headerSource.supplier_name || '';
  document.getElementById('merge-supplier-vat').value = headerSource.supplier_vat || '';
  document.getElementById('merge-doc-type').value = headerSource.doc_type || '';
  document.getElementById('merge-doc-number').value = headerSource.doc_number || '';
  document.getElementById('merge-doc-date').value = headerSource.doc_date || '';
  document.getElementById('merge-doc-time').value = headerSource.doc_time || '';
  document.getElementById('merge-net-amount').value = headerSource.net_amount ?? '';
  document.getElementById('merge-vat-amount').value = headerSource.vat_amount ?? '';
  document.getElementById('merge-total-amount').value = headerSource.total_amount ?? '';

  document.getElementById('merge-sources-summary').textContent = invoice
    ? `Ένωση: υπάρχον τιμολόγιο #${invoice.id} + ${stagingRows.length} στοιχείο(α) σε αναμονή`
    : `Ένωση ${stagingRows.length} στοιχείων σε αναμονή (κανένα δεν έχει καταχωρηθεί ακόμα)`;

  const groups = [];
  if (invoice) groups.push({ label: `Υπάρχον #${invoice.id}`, items: invoice.items || [] });
  stagingRows.forEach(row => groups.push({ label: `Νέο #${row.id}`, items: row.data.items || [] }));

  const keyToGroups = new Map();
  groups.forEach((g, gi) => {
    g.items.forEach(it => {
      const key = mergeItemDupKey(it);
      if (!keyToGroups.has(key)) keyToGroups.set(key, new Set());
      keyToGroups.get(key).add(gi);
    });
  });
  const preferredGroupForKey = new Map();
  for (const [key, groupSet] of keyToGroups) {
    if (groupSet.size < 2) continue;
    let best = -1, bestSize = -1;
    groupSet.forEach(gi => { if (groups[gi].items.length > bestSize) { bestSize = groups[gi].items.length; best = gi; } });
    preferredGroupForKey.set(key, best);
  }

  let itemsHtml = '';
  let anyDuplicate = false;
  groups.forEach((g, gi) => {
    g.items.forEach(it => {
      const key = mergeItemDupKey(it);
      const isDup = keyToGroups.get(key).size > 1;
      if (isDup) anyDuplicate = true;
      const checked = !isDup || preferredGroupForKey.get(key) === gi;
      itemsHtml += mergeItemRowHtml(g.label, it, { checked, duplicate: isDup });
    });
  });
  document.getElementById('merge-items-body').innerHTML = itemsHtml;
  document.getElementById('merge-dup-notice').style.display = anyDuplicate ? '' : 'none';
  recalcMergeHeaderFromItems();

  mergePdfOrder = [];
  if (invoice && invoice.pdf_available) {
    mergePdfOrder.push({
      label: `Τρέχον PDF (τιμολόγιο #${invoice.id})`,
      path: CURRENT_PDF_SENTINEL,
      open: () => window.api.openStoredFile(invoice.source_pdf_filename),
    });
  }
  stagingRows.forEach(row => {
    if (!row.data.source_pdf_path) return;
    const paths = Array.isArray(row.data.source_pdf_path) ? row.data.source_pdf_path : [row.data.source_pdf_path];
    paths.forEach((path, i) => {
      mergePdfOrder.push({
        label: paths.length > 1 ? `Σελίδα ${i + 1} — Νέο #${row.id}` : `Σελίδα — Νέο #${row.id}`,
        path,
        open: () => window.api.openLocalFile(path),
      });
    });
  });
  renderMergePdfOrder();
  updateMergeSumStatus();

  document.getElementById('merge-invoice-modal').classList.add('open');
}

document.getElementById('merge-items-body').addEventListener('input', () => {
  recalcMergeHeaderFromItems();
  updateMergeSumStatus();
});
document.getElementById('merge-net-amount').addEventListener('input', updateMergeSumStatus);

function closeMergeDialog() {
  document.getElementById('merge-invoice-modal').classList.remove('open');
}
document.getElementById('merge-cancel-btn').addEventListener('click', closeMergeDialog);

document.getElementById('merge-commit-btn').addEventListener('click', async () => {
  const numOrNull = (v) => (v === '' || v === null || v === undefined || isNaN(v) ? null : parseFloat(v));
  const itemRows = Array.from(document.getElementById('merge-items-body').querySelectorAll('tr[data-item-row]'));
  const items = itemRows
    .filter(tr => tr.querySelector('[data-f="selected"]').checked)
    .map(tr => {
      const val = (f) => tr.querySelector(`[data-f="${f}"]`).value;
      return {
        description: val('description') || null,
        category: normalizeCategory(val('category')) || null,
        quantity: numOrNull(val('quantity')),
        unit: val('unit') || null,
        unit_price: numOrNull(val('unit_price')),
        value: numOrNull(val('value')),
        vat_pct: numOrNull(val('vat_pct')),
        machine_name: canonicalMachineName(val('machine_name')) || null,
        efk_eligible: tr.querySelector('[data-f="efk_eligible"]').checked,
      };
    });
  if (!items.length) { App.toast('Επίλεξε τουλάχιστον μία γραμμή', 'fail'); return; }

  const header = {
    supplier_name: document.getElementById('merge-supplier-name').value || null,
    supplier_vat: document.getElementById('merge-supplier-vat').value || null,
    doc_type: document.getElementById('merge-doc-type').value || null,
    doc_number: document.getElementById('merge-doc-number').value || null,
    doc_date: document.getElementById('merge-doc-date').value || null,
    doc_time: document.getElementById('merge-doc-time').value || null,
    net_amount: numOrNull(document.getElementById('merge-net-amount').value),
    vat_amount: numOrNull(document.getElementById('merge-vat-amount').value),
    total_amount: numOrNull(document.getElementById('merge-total-amount').value),
  };

  const unlock = _lock(document.getElementById('merge-commit-btn'));
  try {
    await pyCallStrict('merge_documents', {
      target_invoice_id: mergeTargetInvoiceId,
      staging_ids: mergeStagingIds,
      header,
      items,
      pdf_paths_in_order: mergePdfOrder.map(e => e.path),
    });
    App.toast('Η ένωση ολοκληρώθηκε', 'ok');
    closeMergeDialog();
    window.reloadLookups();
    loadStaging();
  } catch (e) {
    App.toast(e.message, 'fail');
  } finally {
    unlock();
  }
});

loadStaging();
