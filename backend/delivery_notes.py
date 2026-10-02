# -*- coding: utf-8 -*-
"""
delivery_notes.py — ένωση Δελτίων Αποστολής NITROCHEM (ΔΙΧΝ) πίσω από το PDF του τιμολογίου που τα αφορά.

Το δελτίο δεν έχει τιμές και έχει τις ίδιες γραμμές/ποσότητες με το τιμολόγιο, άρα ΔΕΝ γίνεται
ξεχωριστή εγγραφή (θα διπλομετριόταν στις αναφορές)· μπαίνει ως επιπλέον σελίδα στο PDF του
τιμολογίου (σελ. 1 το τιμολόγιο, μετά το δελτίο). Αντιστοίχιση μέσω ref_doc_number του τιμολογίου
(«ΔΙΧΝ 20404»). Πριν την ένωση ελέγχεται ότι οι ποσότητες ανά κωδικό ταιριάζουν ακριβώς.
Παίρνει το module `database` ως όρισμα (ίδιο pattern με efk_report.py).

Δεν καλύπτει ακόμα τα δελτία επιστροφής ΔΕΠ0 των πιστωτικών (δεν υπάρχει δείγμα PDF).
"""
import os
import re

import pypdf

from nitrochem_pdf import _num, SUPPLIER_VAT

_HEADER_RE = re.compile(r'Δελτίο Αποστολής\s+ΔΙΧΝ0*(\d+)')
_ITEM_RE = re.compile(r'^(\d{6,9})\s+(.+?)\s+(Κιλ|Τεμ|Μετρ|Λίτ)\s+([\d\.]+,\d+)\s+\S+\s+\S+\s+UN\s*$', re.IGNORECASE)


def parse_delivery_note(path):
    """→ {'ref': 'ΔΙΧΝ 20404', 'quantities': {code: qty}} ή ValueError αν δεν είναι δελτίο ΔΙΧΝ."""
    text = '\n'.join((p.extract_text() or '') for p in pypdf.PdfReader(path).pages)
    m = _HEADER_RE.search(text)
    if not m:
        raise ValueError('Δεν είναι Δελτίο Αποστολής ΔΙΧΝ της NITROCHEM')
    quantities = {}
    for line in text.split('\n'):
        im = _ITEM_RE.match(line.strip())
        if im:
            quantities[im.group(1)] = round(quantities.get(im.group(1), 0) + _num(im.group(4)), 3)
    if not quantities:
        raise ValueError('Δεν βρέθηκε καμία γραμμή είδους στο δελτίο')
    return {'ref': f'ΔΙΧΝ {m.group(1)}', 'quantities': quantities}


def _pdf_contains(path, needle):
    try:
        text = '\n'.join((p.extract_text() or '') for p in pypdf.PdfReader(path).pages)
    except Exception:  # noqa: BLE001
        return False
    return needle in text


def attach_delivery_notes(database, file_paths, apply=False):
    """Ένα αποτέλεσμα ανά αρχείο: {'file', 'status', 'message', 'invoice_id', 'doc_number'}.
    status: ready/applied | no_invoice | qty_mismatch | already | no_pdf | not_da | error.
    apply=False είναι dry-run (τίποτα δεν αλλάζει)."""
    results = []
    for path in file_paths:
        res = {'file': os.path.basename(path), 'status': None, 'message': '', 'invoice_id': None, 'doc_number': None}
        results.append(res)
        try:
            da = parse_delivery_note(path)
        except Exception as e:  # noqa: BLE001
            res.update(status='not_da', message=str(e))
            continue
        with database.get_db() as conn:
            invs = conn.execute(
                '''SELECT i.id, i.doc_number, i.source_pdf_filename FROM tbl_invoices i
                   JOIN tbl_suppliers s ON s.id = i.supplier_id
                   WHERE i.ref_doc_number = ? AND REPLACE(s.vat_number, ' ', '') = ?''',
                (da['ref'], SUPPLIER_VAT)).fetchall()
            if len(invs) != 1:
                res.update(status='no_invoice',
                           message=f'{da["ref"]}: ' + ('δεν υπάρχει ακόμα τιμολόγιο που να το αναφέρει' if not invs
                                                      else f'{len(invs)} τιμολόγια το αναφέρουν — χειροκίνητα'))
                continue
            inv = invs[0]
            items = {}
            for r in conn.execute('SELECT code, quantity FROM tbl_invoice_items WHERE invoice_id=?', (inv['id'],)):
                items[r['code']] = round(items.get(r['code'], 0) + (r['quantity'] or 0), 3)
        res.update(invoice_id=inv['id'], doc_number=inv['doc_number'])
        if not inv['source_pdf_filename']:
            res.update(status='no_pdf', message=f'{da["ref"]}: το τιμολόγιο {inv["doc_number"]} δεν έχει συνδεδεμένο PDF')
            continue
        old = os.path.join(database.PDF_STORE_DIR, inv['source_pdf_filename'])
        if not os.path.exists(old):
            res.update(status='no_pdf', message=f'{da["ref"]}: λείπει το αρχείο PDF του τιμολογίου {inv["doc_number"]}')
            continue
        # Στη σελίδα του δελτίου ο αριθμός είναι συμπληρωμένος με μηδενικά («ΔΙΧΝ00020404»)
        if _pdf_contains(old, f'ΔΙΧΝ{int(da["ref"].split()[1]):08d}'):
            res.update(status='already', message=f'{da["ref"]}: είναι ήδη μέσα στο PDF του τιμολογίου {inv["doc_number"]}')
            continue
        if da['quantities'] != items:
            res.update(status='qty_mismatch',
                       message=f'{da["ref"]} ↔ ΤΙΠ {inv["doc_number"]}: οι ποσότητες δεν ταιριάζουν (δελτίο {da["quantities"]} / τιμολόγιο {items})')
            continue
        if apply:
            database._merge_pdfs_and_attach(inv['id'], [database.CURRENT_PDF_SENTINEL, path], old_path=old)
            res.update(status='applied', message=f'{da["ref"]} → πίσω από το ΤΙΠ {inv["doc_number"]}')
        else:
            res.update(status='ready', message=f'{da["ref"]} → πίσω από το ΤΙΠ {inv["doc_number"]}')
    return results
