# -*- coding: utf-8 -*-
"""
expvault_export.py — εξαγωγή των γραμμών «Εκρηκτικά» του invoicebook σε αρχείο JSON για
την «Εισαγωγή JSON/CSV» του expvault (βλ. expvault/backend/import_data.py's
_build_suggested — ένα object ανά παραστατικό, με grammes[]).

Ειδικό για το expvault, όχι γενικό schema — γι' αυτό ζει εδώ και όχι στο invoicebook's
database.py (κανόνας του CLAUDE.md). Αποφάσεις/σκεπτικό: TODO.md, «Batch export
τιμολογίων εκρηκτικών από invoicebook προς expvault»:
- Μόνο γραμμές με category «Εκρηκτικά» ανά τιμολόγιο, όχι όλο το τιμολόγιο.
- Χωρίς τιμές/αξίες (το expvault δεν έχει έννοια τιμής).
- ΑΠΟ ΦΥΛΑΞΗ → ΕΙΣΑΓΩΓΗ, ΠΡΟΣ ΦΥΛΑΞΗ → ΕΠΙΣΤΡΟΦΗ (ένας κύκλος φύλαξης αλληλοαναιρείται
  στη χρήση άδειας), με παρατήρηση «ΑΠΟ/ΠΡΟΣ ΦΥΛΑΞΗ». Η κατεύθυνση θέλει πάντα έλεγχο στο
  PDF από τον χειριστή (needs_check) — γι' αυτό ο τύπος είναι μόνο πρόταση, αλλάζει στο UI.
- agora_ref κενό (το συμπληρώνει το interactive βήμα του expvault)· ταξινόμηση κατά
  ημερομηνία, με τις ΕΙΣΑΓΩΓΕΣ πριν από τις ΕΠΙΣΤΡΟΦΕΣ της ίδιας μέρας.
- Κάθε επιτυχημένη εξαγωγή καταγράφεται (invoicebook tbl_invoice_exports, target
  'expvault')· όσα έχουν ήδη εξαχθεί εμφανίζονται αποεπιλεγμένα στο UI, ώστε να μη
  καταχωρηθούν δύο φορές στο νόμιμο βιβλίο.
"""
import os
import json
import re
import unicodedata
import uuid
from datetime import datetime

from expvault_materials import canonical_material, material_key

CATEGORY = 'Εκρηκτικά'
TARGET = 'expvault'
TIPOI = ('ΕΙΣΑΓΩΓΗ', 'ΕΠΙΣΤΡΟΦΗ')
FYLAXI_NOTE = {'ΕΙΣΑΓΩΓΗ': 'ΑΠΟ ΦΥΛΑΞΗ', 'ΕΠΙΣΤΡΟΦΗ': 'ΠΡΟΣ ΦΥΛΑΞΗ'}

# ΑΦΜ προμηθευτή (invoicebook) → όνομα προμηθευτή όπως το ξέρει ήδη το expvault (εκεί είναι
# απλή ετικέτα, χωρίς ΑΦΜ). NITROCHEM: Ε.Π.Ε. → Α.Ε. στις 08/09/2017, ίδιο ΑΦΜ — στο invoicebook
# μένει «Ε.Π.Ε.» (ιστορικό όνομα), στο expvault «Α.Ε.» (αλλιώς διπλός προμηθευτής).
_EXPVAULT_SUPPLIER_NAMES = {'800385641': 'NITROCHEM Α.Ε.'}

# Γραμμές που δεν είναι πραγματικό υλικό (ίδιο μοτίβο με το Λιπαντικά cleanup).
_NON_MATERIAL = re.compile(r'ΜΕΤΑΦΟΡ|ΚΟΜΙΣΤΡ|ΕΙΣΦΟΡ|ΑΝΑΚΥΚΛ|ΕΞΟΔ|ΕΚΠΤΩΣ|Φ\.?Π\.?Α')

# invoicebook μονάδα (ελεύθερο κείμενο, το IMPORT_PROMPT ζητάει L/kg/ΤΕΜ/m) → expvault.
_UNITS = {
    'KG': 'Κιλ', 'ΚΓ': 'Κιλ', 'ΚΙΛ': 'Κιλ', 'ΚΙΛΑ': 'Κιλ', 'ΚΙΛΟ': 'Κιλ',
    'ΤΕΜ': 'Τεμ', 'TEM': 'Τεμ', 'ΤΕΜΑΧΙΑ': 'Τεμ', 'ΤΕΜΑΧΙΟ': 'Τεμ', 'PCS': 'Τεμ',
    'M': 'Μετρ', 'Μ': 'Μετρ', 'ΜΕΤ': 'Μετρ', 'ΜΕΤΡ': 'Μετρ', 'ΜΕΤΡΑ': 'Μετρ', 'ΜΕΤΡΟ': 'Μετρ',
}

_ADEIA_RE = re.compile(r'Άδεια:\s*([^,\n]+?)\s*,\s*Εκδούσα αρχή:\s*([^\n]+)', re.IGNORECASE)


def _norm(s):
    """Κεφαλαία χωρίς τόνους — για συγκρίσεις κειμένου (κατηγορία, φράσεις ΦΥΛΑΞΗΣ)."""
    s = unicodedata.normalize('NFD', s or '')
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').upper()


def _unit(raw):
    key = _norm(raw).replace('.', '').strip()
    return _UNITS.get(key)


def _propose_tipos(doc_type, notes):
    """(tipos, paratirishis, is_fylaxi, reason) — πρόταση, ο χειριστής την επιβεβαιώνει."""
    text = _norm(f'{doc_type or ""}\n{notes or ""}')
    pros, apo = 'ΠΡΟΣ ΦΥΛΑΞΗ' in text, 'ΑΠΟ ΦΥΛΑΞΗ' in text
    if pros and not apo:
        return 'ΕΠΙΣΤΡΟΦΗ', FYLAXI_NOTE['ΕΠΙΣΤΡΟΦΗ'], True, 'Αναγράφει «ΠΡΟΣ ΦΥΛΑΞΗ»'
    if apo and not pros:
        return 'ΕΙΣΑΓΩΓΗ', FYLAXI_NOTE['ΕΙΣΑΓΩΓΗ'], True, 'Αναγράφει «ΑΠΟ ΦΥΛΑΞΗ»'
    if pros and apo:
        return 'ΕΙΣΑΓΩΓΗ', FYLAXI_NOTE['ΕΙΣΑΓΩΓΗ'], True, 'Αναγράφει ΚΑΙ «ΠΡΟΣ» ΚΑΙ «ΑΠΟ ΦΥΛΑΞΗ» — διάλεξε'
    if 'ΦΥΛΑΞ' in text:
        return 'ΕΙΣΑΓΩΓΗ', FYLAXI_NOTE['ΕΙΣΑΓΩΓΗ'], True, 'Αναφέρει φύλαξη χωρίς κατεύθυνση — διάλεξε'
    if 'ΠΙΣΤΩΤΙΚ' in text or 'ΕΠΙΣΤΡΟΦ' in text:
        return 'ΕΠΙΣΤΡΟΦΗ', '', False, 'Πιστωτικό / επιστροφή'
    return 'ΕΙΣΑΓΩΓΗ', '', False, 'Αγορά'


def _vat_key(vat):
    v = re.sub(r'\D', '', str(vat or ''))
    return v or None


def _export_identity(inv, tipos):
    """(ημερομηνία, αριθμός, προμηθευτής, reason, warnings) που γράφονται στο expvault.

    Τιμολόγια/πιστωτικά με «Σχετ. Παραστατικό» (migration 007): το νόμιμο βιβλίο δουλεύει με το
    ΔΕΛΤΙΟ ΑΠΟΣΤΟΛΗΣ, όχι με το τιμολόγιο — ημερομηνία και αριθμός του Δ.Α. (εισαγωγή:
    «ΔΙΧΝ 19858», 6/3· επιστροφή: ημερομηνία ΔΕΠ και δικό μας Δ.Α. «ΔΕ 9»). Προμηθευτής:
    στις εισαγωγές αυτός του τιμολογίου (με το όνομα που ξέρει το expvault), στις επιστροφές ο
    πελάτης όπως τυπώνεται (ο «προμηθευτής» είναι όποιος εξέδωσε το έντυπο — δικό μας Δ.Α.).
    Χωρίς Σχετ. Παραστατικό (ιστορικά Δ.Α.) μένει η παλιά συμπεριφορά."""
    if not inv['ref_doc_number']:
        return inv['doc_date'], inv['doc_number'], inv['supplier_name'] or '', None, []
    warnings = []
    credit = tipos == 'ΕΠΙΣΤΡΟΦΗ'
    date = inv['ref_doc_date']
    if not date:
        warnings.append('Χωρίς ημερομηνία Σχετ. Παραστατικού — χρησιμοποιείται η ημερομηνία του τιμολογίου')
        date = inv['doc_date']
    if credit:
        number = inv['own_doc_number']
        if not number:
            warnings.append('Πιστωτικό χωρίς δικό μας Δ.Α. επιστροφής — χρησιμοποιείται το Σχετ. Παραστατικό')
            number = inv['ref_doc_number']
        who = inv['customer_name']
        if not who:
            warnings.append('Πιστωτικό χωρίς όνομα πελάτη — χρησιμοποιείται ο προμηθευτής του τιμολογίου')
            who = inv['supplier_name'] or ''
        reason = f'Πιστωτικό — επιστροφή με δικό μας Δ.Α. ({number}), ημερομηνία του {inv["ref_doc_number"]}'
    else:
        number = inv['ref_doc_number']
        who = _EXPVAULT_SUPPLIER_NAMES.get(_vat_key(inv['vat_number']), inv['supplier_name'] or '')
        reason = f'Τιμολόγιο — κίνηση με το Σχετ. Δ.Α. ({number})'
    return date, number, who, reason, warnings


def preview(db, date_from=None, date_to=None):
    """Ένα dict ανά τιμολόγιο που έχει τουλάχιστον μία γραμμή «Εκρηκτικά»."""
    target = _norm(CATEGORY)
    where, params = ['1=1'], []
    if date_from:
        where.append('i.doc_date >= ?'); params.append(date_from)
    if date_to:
        where.append('i.doc_date <= ?'); params.append(date_to)
    with db.get_db() as conn:
        invoices = conn.execute(
            f'''SELECT i.id, i.doc_date, i.doc_type, i.doc_number, i.notes, i.source_pdf_filename,
                       i.ref_doc_number, i.ref_doc_date, i.own_doc_number, i.customer_name,
                       s.name AS supplier_name, s.vat_number
                FROM tbl_invoices i LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
                WHERE {' AND '.join(where)} ORDER BY i.doc_date, i.id''', params
        ).fetchall()
        items_by_inv = {}
        for it in conn.execute(
            'SELECT invoice_id, description, quantity, unit, category FROM tbl_invoice_items ORDER BY id'
        ).fetchall():
            if _norm(it['category']).strip() == target:
                items_by_inv.setdefault(it['invoice_id'], []).append(dict(it))

    exports = db.get_invoice_exports(TARGET)
    docs = []
    for inv in invoices:
        items = items_by_inv.get(inv['id'])
        if not items:
            continue
        tipos, paratirishis, is_fylaxi, reason = _propose_tipos(inv['doc_type'], inv['notes'])
        x_date, x_number, x_who, x_reason, id_warnings = _export_identity(inv, tipos)
        if x_reason:
            reason = x_reason
        m = _ADEIA_RE.search(inv['notes'] or '')
        grammes, excluded, warnings = [], [], []
        for it in items:
            desc = (it['description'] or '').strip()
            if _NON_MATERIAL.search(_norm(desc)):
                excluded.append({'description': desc, 'reason': 'δεν είναι υλικό'})
                continue
            if it['quantity'] is None or it['quantity'] <= 0:
                excluded.append({'description': desc, 'reason': 'χωρίς ποσότητα'})
                continue
            monada = _unit(it['unit'])
            if not monada:
                warnings.append(f'Άγνωστη μονάδα «{it["unit"] or "—"}» στο «{desc}» — θα μπει ως Κιλ')
            # Το όνομα του expvault (ταίριασμα κατά κλειδί) — αλλιώς .upper() + προειδοποίηση,
            # γιατί ένα άγνωστο όνομα θα έφτιαχνε ΝΕΟ υλικό στο expvault.
            known = canonical_material(desc)
            if not known:
                warnings.append(f'Υλικό «{desc}» εκτός καταλόγου expvault — θα δημιουργηθεί νέο υλικό εκεί')
            grammes.append({'onoma': known or desc.upper(), 'posotita': it['quantity'], 'monada': monada or 'Κιλ'})
        if not m:
            warnings.append('Δεν βρέθηκε «Άδεια: …, Εκδούσα αρχή: …» στις σημειώσεις')
        warnings.extend(id_warnings)
        if not x_number:
            warnings.append('Χωρίς αριθμό παραστατικού')
        if not grammes:
            warnings.append('Καμία γραμμή υλικού — δεν θα εξαχθεί')
        docs.append({
            'invoice_id': inv['id'], 'doc_date': inv['doc_date'], 'doc_type': inv['doc_type'],
            'doc_number': inv['doc_number'], 'supplier_name': inv['supplier_name'],
            'export_date': x_date, 'export_number': x_number, 'export_promitheftis': x_who,
            'source_pdf_filename': inv['source_pdf_filename'],
            'tipos': tipos, 'paratirishis': paratirishis, 'is_fylaxi': is_fylaxi,
            'needs_check': is_fylaxi, 'reason': reason,
            'adeia': m.group(1).strip() if m else '', 'ekdousa_archi': m.group(2).strip() if m else '',
            'grammes': grammes, 'excluded': excluded, 'warnings': warnings,
            'exported': exports.get(inv['id']),
        })
    return docs


def build(docs, tipos_overrides=None, exclude_ids=None):
    """Τα docs του preview → λίστα expvault objects. tipos_overrides: {invoice_id: tipos}
    από τον χειριστή· exclude_ids: τιμολόγια που αποεπιλέχθηκαν."""
    return [obj for _, obj in _build_pairs(docs, tipos_overrides, exclude_ids)]


def _build_pairs(docs, tipos_overrides=None, exclude_ids=None):
    """(invoice_id, expvault object) -- το invoice_id δεν μπαίνει στο αρχείο, χρειάζεται
    μόνο για την καταγραφή της εξαγωγής."""
    tipos_overrides = {int(k): v for k, v in (tipos_overrides or {}).items()}
    exclude_ids = {int(i) for i in (exclude_ids or [])}
    out = []
    for d in docs:
        if d['invoice_id'] in exclude_ids or not d['grammes']:
            continue
        tipos = tipos_overrides.get(d['invoice_id'], d['tipos'])
        if tipos not in TIPOI:
            raise ValueError(f'Μη έγκυρος τύπος «{tipos}» για το τιμολόγιο #{d["invoice_id"]}')
        # Αλλαγή κατεύθυνσης σε έγγραφο φύλαξης αλλάζει και την παρατήρηση.
        paratirishis = FYLAXI_NOTE[tipos] if d['is_fylaxi'] else d['paratirishis']
        out.append((d['invoice_id'], {
            'imerominia': d['export_date'] or '',
            'tipos': tipos,
            'arithmos_parstatikou': d['export_number'] or '',
            'adeia': d['adeia'],
            'ekdousa_archi': d['ekdousa_archi'],
            'promitheftis': d['export_promitheftis'] or '',
            'paratirishis': paratirishis,
            'agora_ref': '',
            'grammes': d['grammes'],
        }))
    # Η αγορά πρέπει να μπει στο expvault πριν από την επιστροφή της (interactive linking).
    out.sort(key=lambda p: (p[1]['imerominia'], TIPOI.index(p[1]['tipos'])))
    return out


def new_export_id():
    """Μοναδικό αναγνωριστικό εξαγωγής — γράφεται σε κάθε παραστατικό του αρχείου και στο ιστορικό, ώστε το
    αποδεικτικό εισαγωγής του ExpVault+ να ταιριάξει με τη συγκεκριμένη εξαγωγή."""
    return 'EX-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:6]


def export_to_file(db, path, date_from=None, date_to=None, tipos_overrides=None, exclude_ids=None):
    """Ξαναϋπολογίζει το preview στο backend (πηγή αλήθειας η βάση, όχι ό,τι κράτησε το UI)
    και γράφει το αρχείο. Κάθε παραστατικό παίρνει `export_id` (κοινό για όλη την εξαγωγή) και
    `source_invoice_id` (το id του τιμολογίου), που το ExpVault+ κρατά και επιστρέφει στο αποδεικτικό εισαγωγής."""
    pairs = _build_pairs(preview(db, date_from, date_to), tipos_overrides, exclude_ids)
    if not pairs:
        raise ValueError('Δεν υπάρχει κανένα παραστατικό προς εξαγωγή')
    eid = new_export_id()
    lines_by_invoice = {}
    for inv_id, obj in pairs:
        obj['export_id'] = eid
        obj['source_invoice_id'] = inv_id
        lines_by_invoice[inv_id] = [{'onoma': g['onoma'], 'posotita': g['posotita']} for g in obj['grammes']]
    objs = [obj for _, obj in pairs]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(objs, f, ensure_ascii=False, indent=2)
    # Καταγραφή ΜΟΝΟ αφού γραφτεί επιτυχώς το αρχείο.
    db.record_invoice_exports(TARGET, [i for i, _ in pairs], os.path.basename(path),
                              export_id=eid, lines_by_invoice=lines_by_invoice)
    return {
        'path': path, 'documents': len(objs), 'lines': sum(len(o['grammes']) for o in objs),
        'eisagoges': sum(o['tipos'] == 'ΕΙΣΑΓΩΓΗ' for o in objs),
        'epistrofes': sum(o['tipos'] == 'ΕΠΙΣΤΡΟΦΗ' for o in objs),
        'export_id': eid,
    }


# ── ΑΠΟΔΕΙΚΤΙΚΟ ΕΙΣΑΓΩΓΗΣ ────────────────────────────────────────────────────────
def _lines_map(lines):
    """{κλειδί υλικού: άθροισμα ποσότητας} — η σύγκριση αγνοεί σειρά, κεφαλαία/κενά/σημεία στίξης στο όνομα."""
    out = {}
    for l in lines:
        k = material_key(l.get('onoma'))
        out[k] = round(out.get(k, 0) + float(l.get('posotita') or 0), 3)
    return out


def _utc_iso(ts):
    """'2026-10-01 14:30:00' (datetime('now') του ExpVault+, UTC) → ISO με ζώνη, όπως το _now() του invoicebook."""
    if not ts:
        return None
    ts = str(ts).strip().replace(' ', 'T')
    return ts if re.search(r'(Z|[+-]\d\d:\d\d)$', ts) else ts + '+00:00'


def load_receipt(db, path):
    """Φορτώνει αρχείο-απόδειξη εισαγωγής του ExpVault+ (format 'expvault-import-receipt') και, για κάθε εξαγωγή που
    αναγνωρίζει (export_id), συγκρίνει ανά τιμολόγιο τις γραμμές που εξήχθησαν με αυτές που πράγματι καταχωρήθηκαν:
    'ok' = ίδιες, 'mismatch' = διαφορές (καταγράφονται στο import_note). Τιμολόγια που δεν υπάρχουν στην απόδειξη μένουν
    «εκκρεμεί». Ξαναφόρτωση της ίδιας ή νεότερης απόδειξης ξαναϋπολογίζει (idempotent)."""
    with open(path, 'r', encoding='utf-8-sig') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as ex:
            raise ValueError(f'Μη έγκυρο JSON: {ex}')
    if not isinstance(data, dict) or data.get('format') != 'expvault-import-receipt':
        raise ValueError('Το αρχείο δεν είναι απόδειξη εισαγωγής του ExpVault+ (λάθος «format»).')
    if data.get('version') != 1:
        raise ValueError(f'Μη υποστηριζόμενη έκδοση απόδειξης: {data.get("version")!r}')
    name = os.path.basename(path)
    summary = {'ok': 0, 'mismatch': 0, 'pending': 0, 'unknown_exports': [], 'unknown_documents': 0, 'details': []}
    for ex in data.get('exports') or []:
        eid = ex.get('export_id')
        rows = db.get_export_rows(eid) if eid else []
        if not rows:
            summary['unknown_exports'].append(eid)
            continue
        docs_by_src = {}
        for doc in ex.get('documents') or []:
            docs_by_src.setdefault(str(doc.get('source_invoice_id')), []).append(doc)
        known = {str(r['invoice_id']) for r in rows}
        summary['unknown_documents'] += len([s for s in docs_by_src if s not in known])
        for row in rows:
            docs = docs_by_src.get(str(row['invoice_id']))
            if not docs:
                summary['pending'] += 1
                continue
            got = _lines_map([l for d in docs for l in d.get('lines') or []])
            imported_at = _utc_iso(min((d.get('imported_at') or '') for d in docs) or None)
            if row['lines_json']:
                exp_lines = json.loads(row['lines_json'])
                exp = _lines_map(exp_lines)
                if exp == got:
                    status, note = 'ok', None
                else:
                    names = {material_key(l.get('onoma')): l.get('onoma') for l in exp_lines}
                    names.update({material_key(l.get('onoma')): l.get('onoma')
                                  for d_ in docs for l in d_.get('lines') or [] if material_key(l.get('onoma')) not in names})
                    parts = []
                    for k in sorted(set(exp) | set(got)):
                        if exp.get(k) != got.get(k):
                            parts.append(f"{names.get(k, k)}: εξήχθη {exp.get(k, '—')} / καταχωρήθηκε {got.get(k, '—')}")
                    status, note = 'mismatch', '; '.join(parts)[:500]
            else:
                status, note = 'ok', 'Χωρίς καταγεγραμμένες γραμμές εξαγωγής — επιβεβαιώθηκε μόνο η ύπαρξη του παραστατικού'
            db.set_export_import_status(row['id'], status, imported_at, note, name)
            summary[status] += 1
            if status == 'mismatch':
                summary['details'].append({'invoice_id': row['invoice_id'], 'note': note})
    return summary
