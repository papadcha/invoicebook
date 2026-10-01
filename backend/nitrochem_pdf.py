# -*- coding: utf-8 -*-
"""
nitrochem_pdf.py — deterministic parser για τα ηλεκτρονικά PDF τιμολογίων/πιστωτικών της
NITROCHEM Α.Ε. (πρότυπο EpsilonDigital, text layer — όχι σαρωμένα). Χωρίς AI: οι ποσότητες
και οι τιμές ενός νόμιμου βιβλίου εκρηκτικών δεν πρέπει να περνάνε από εικασία.

Επιβεβαιώθηκε (2026-10-01) σε 52 πραγματικά PDF: 46 «Τιμολόγιο Πώλησης» + 6 «Πιστωτικό
Τιμολόγιο», όλα 1 σελίδα. Το parse_pdf επιστρέφει ένα dict με το ΙΔΙΟ σχήμα που έχει μια
γραμμή του JSON/CSV import (βλ. bridge._parse_import_file), ώστε προεπισκόπηση, staging και
επιβεβαίωση να μείνουν ως έχουν:

  header : supplier_name/vat, doc_type, doc_number, doc_date (ISO), customer_*, payment_method,
           net/vat/total_amount, notes («Άδεια: …, Εκδούσα αρχή: …»)
  σχετικά: ref_doc_number/ref_doc_date («Σχετ. Παραστ.» — το Δ.Α. που αναφέρει το τιμολόγιο),
           own_doc_number (μόνο πιστωτικά — το δικό μας Δ.Α. επιστροφής, π.χ. «ΔΕ 9»)
  items  : code, description, unit, quantity, unit_price, value, vat_pct, category='Εκρηκτικά'

Πρόσημο: στο πιστωτικό η κεφαλίδα (καθαρή/ΦΠΑ/σύνολο) είναι ΑΡΝΗΤΙΚΗ, ενώ ποσότητα και αξία
γραμμής μένουν ΘΕΤΙΚΕΣ (η αφαίρεση γίνεται ανά τύπο εγγράφου στις αναφορές).

Ό,τι δεν επαληθεύεται (άθροισμα γραμμών, ΦΠΑ, σύνολο στο κείμενο, ύπαρξη Σχετ. Παραστ.)
δεν περνάει σιωπηλά: μπαίνει στο 'parse_warnings' της γραμμής.
"""
import os
import re

from expvault_materials import canonical_material

try:
    import pypdf
except ImportError:  # pragma: no cover — το requirements.txt το έχει
    pypdf = None

SUPPLIER_NAME = 'NITROCHEM Α.Ε.'
SUPPLIER_VAT = '800385641'
CATEGORY = 'Εκρηκτικά'

_UNITS = {'ΚΙΛ': 'kg', 'ΚΙΛΑ': 'kg', 'ΤΕΜ': 'ΤΕΜ', 'ΜΕΤΡ': 'm', 'ΜΕΤΡΑ': 'm', 'ΛΙΤ': 'L'}

_NUM = r'-?[\d\.]+,\d+'
# Η αξία έχει ΠΑΝΤΑ 2 δεκαδικά και μπορεί να είναι κολλημένη με τον κωδικό («1.462,5040000000»):
# ο αυστηρός αριθμός αποτρέπει να «φάει» ψηφία του κωδικού.
_VALUE = r'\d{1,3}(?:\.\d{3})*,\d{2}'
_ITEM_RE = re.compile(
    rf'^({_NUM})\s+({_VALUE})\s*(\d{{6,9}})\s+(.+?)\s+(Κιλ|Τεμ|Μετρ|Λίτ)\s+({_NUM})\s+0,\s?0+\s*$',
    re.IGNORECASE,
)
_HEADER_RE = re.compile(
    r'(Πιστωτικό Τιμολόγιο|Τιμολόγιο Πώλησης)\s+(\d+)\s*\n\s*(\d{2}/\d{2}/\d{4})')
_REL_RE = re.compile(r'([Α-ΩA-Z0-9]{2,8}\s*[-–]\s*\d+)\s*[-–]\s*(\d{1,2}/\d{1,2}/\d{4})')
_OWN_RE = re.compile(r'^\s*(ΔΕ|ΔΑΠ)\s+(\d+)\s*$', re.MULTILINE)
_VAT_RATES = (24, 13, 17, 9, 6, 0)


def _num(s):
    return float(s.replace('.', '').replace(',', '.'))


def _fmt(x):
    """1234.5 → '1.234,50' (ελληνική μορφή, όπως τυπώνεται στα PDF)."""
    return f'{abs(x):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _iso(d):
    day, month, year = d.split('/')
    return f'{year}-{int(month):02d}-{int(day):02d}'


def _extract_text(path):
    if pypdf is None:
        raise RuntimeError('Η βιβλιοθήκη pypdf δεν είναι εγκατεστημένη.')
    reader = pypdf.PdfReader(path)
    return '\n'.join((p.extract_text() or '') for p in reader.pages)


def parse_text(text, path=None):
    """Η καθαρή λογική (χωρίς αρχείο) — ξεχωριστή ώστε να ελέγχεται εύκολα."""
    warnings = []
    m = _HEADER_RE.search(text)
    if not m:
        raise ValueError('Δεν αναγνωρίστηκε ως τιμολόγιο/πιστωτικό NITROCHEM (δεν βρέθηκε επικεφαλίδα).')
    doc_type, doc_number, doc_date = m.group(1), m.group(2), _iso(m.group(3))
    is_credit = doc_type.startswith('Πιστωτικό')
    lines = [l.strip() for l in text.split('\n')]

    # ── Γραμμές ειδών ────────────────────────────────────────────────────────
    items = []
    for line in lines:
        im = _ITEM_RE.match(line)
        if not im:
            continue
        price, value, code, desc, unit, qty = im.groups()
        items.append({
            'code': code,
            'description': desc.strip(),
            'unit': _UNITS.get(unit.upper(), unit),
            'quantity': _num(qty),
            'unit_price': _num(price),
            'value': _num(value),
            # Μόνο υλικά του καταλόγου του expvault μαρκάρονται «Εκρηκτικά» — ό,τι άλλο
            # (π.χ. ΠΕΝΣΕΣ/CAP CRIMPER, εργαλείο) μένει χωρίς κατηγορία, να το ορίσει ο
            # χειριστής στην προεπισκόπηση, αντί να μπει σιωπηλά στο νόμιμο βιβλίο.
            'category': CATEGORY if canonical_material(desc) else None,
            'efk_eligible': False,
        })
    if not items:
        raise ValueError('Δεν βρέθηκε καμία γραμμή είδους στο PDF.')
    foreign = [i['description'] for i in items if not i['category']]
    if foreign:
        warnings.append('Είδος εκτός καταλόγου expvault (δεν σημειώθηκε «Εκρηκτικά»): ' + '; '.join(foreign))
    unmatched = [l for l in lines if re.search(r'\d{6,9}\s', l) and re.search(r'(Κιλ|Τεμ|Μετρ)', l)
                 and not _ITEM_RE.match(l)]
    if unmatched:
        warnings.append(f'{len(unmatched)} γραμμή/ές που μοιάζουν με είδος δεν διαβάστηκαν: {unmatched[0][:60]}')

    # ── Σύνολα: καθαρή = Σ γραμμών· ο συντελεστής ΦΠΑ βρίσκεται από το ποιο ζευγάρι
    #    (ΦΠΑ, σύνολο) εμφανίζεται πραγματικά στο κείμενο ──────────────────────────
    net = round(sum(i['value'] for i in items), 2)
    rate = None
    for r in _VAT_RATES:
        vat = round(net * r / 100, 2)
        if _fmt(vat) in text and _fmt(net + vat) in text and _fmt(net) in text:
            rate = r
            break
    if rate is None:
        warnings.append('Τα σύνολα (καθαρή/ΦΠΑ/πληρωτέο) δεν επαληθεύτηκαν με το άθροισμα των γραμμών.')
        rate = 24
    vat = round(net * rate / 100, 2)
    total = round(net + vat, 2)
    for i in items:
        i['vat_pct'] = rate
    sign = -1 if is_credit else 1

    # ── Σχετικά παραστατικά ──────────────────────────────────────────────────
    rm = _REL_RE.search(text)
    if not rm:
        warnings.append('Δεν βρέθηκε «Σχετ. Παραστ.» (αριθμός/ημερομηνία Δ.Α.).')
    own = _OWN_RE.search(text) if is_credit else None
    if is_credit and not own:
        warnings.append('Πιστωτικό χωρίς δικό μας Δ.Α. επιστροφής (ΔΕ/ΔΑΠ) στο σχόλιο.')

    # ── Πελάτης (ο 5ψήφιος κωδικός πελάτη είναι μόνος σε γραμμή, ακολουθεί η επωνυμία) ──
    customer_name = customer_vat = customer_doy = payment = None
    for idx, l in enumerate(lines):
        if re.match(r'^\d{5}$', l) and idx + 1 < len(lines):
            customer_name = lines[idx + 1] or None
            break
    for l in lines:
        vm = re.match(r'^(\d{9})\s+([Α-ΩΆ-Ώ][Α-ΩΆ-Ώ ]*)$', l)
        if vm:
            customer_vat, customer_doy = vm.group(1), vm.group(2).strip()
            break
    for l in lines:
        if re.match(r'^ΕΠΙ ΠΙΣΤΩΣΕΙ', l):
            payment = l
            break

    # ── Άδεια + εκδούσα αρχή (αριθμός άδειας μόνος σε γραμμή, ακολουθεί «Δ.Α. <περιοχή>») ──
    notes = None
    for idx, l in enumerate(lines):
        if re.match(r'^Δ\.Α\.\s+\S+', l) and idx > 0 and re.match(r'^\d{4,6}$', lines[idx - 1]):
            notes = f'Άδεια: {lines[idx - 1]}, Εκδούσα αρχή: {l}'
            break

    row = {
        'supplier_name': SUPPLIER_NAME,
        'supplier_vat': SUPPLIER_VAT,
        'doc_type': doc_type,
        'doc_number': doc_number,
        'doc_date': doc_date,
        'customer_name': customer_name,
        'customer_vat': customer_vat,
        'customer_doy': customer_doy,
        'payment_method': payment,
        'net_amount': round(sign * net, 2),
        'vat_amount': round(sign * vat, 2),
        'total_amount': round(sign * total, 2),
        'notes': notes,
        'ref_doc_number': rm.group(1) if rm else None,
        'ref_doc_date': _iso(rm.group(2)) if rm else None,
        'own_doc_number': f'{own.group(1)} {own.group(2)}' if own else None,
        'items': items,
    }
    if path:
        row['source_pdf_path'] = path
    if warnings:
        row['parse_warnings'] = warnings
    return row


def parse_pdf(path):
    return parse_text(_extract_text(path), path=path)


def parse_pdfs(paths):
    """Πολλά αρχεία: {'rows': [...], 'errors': [{'file', 'error'}]} — ένα προβληματικό PDF δεν
    ακυρώνει τα υπόλοιπα."""
    rows, errors = [], []
    for p in paths:
        try:
            rows.append(parse_pdf(p))
        except Exception as e:  # noqa: BLE001 — το μήνυμα πάει στον χρήστη
            errors.append({'file': os.path.basename(p), 'error': str(e)})
    return {'rows': rows, 'errors': errors}
