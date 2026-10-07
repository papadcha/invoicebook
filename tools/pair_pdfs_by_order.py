# -*- coding: utf-8 -*-
"""
pair_pdfs_by_order.py — συνδυάζει έναν φάκελο με πολλά PDF τιμολογίων με ΕΝΑ JSON
array (η απάντηση του Gemini όταν του ανεβάζεις πολλά PDF μαζί σε ένα prompt) βάσει
ΣΕΙΡΑΣ, όχι ονόματος αρχείου. Παράγει combined_import.json έτοιμο για μαζική εισαγωγή
στο invoicebook, με source_pdf_path συμπληρωμένο σε κάθε τιμολόγιο.

ΠΡΟΫΠΟΘΕΣΗ (ΣΗΜΑΝΤΙΚΟ): τα PDF πρέπει να ανέβηκαν στο Gemini με την ΙΔΙΑ σειρά που
έχουν αλφαβητικά μέσα στον φάκελο (π.χ. επιλογή όλων στον Explorer, που είναι ήδη
αλφαβητικά, και μαζικό drag-and-drop στο Gemini). Το script δεν μπορεί να το
επαληθεύσει αυτό μόνο του — γι' αυτό τυπώνει τη λίστα ταιριασμάτων (PDF όνομα +
προμηθευτής/ημερομηνία/ποσό από το JSON) πριν γράψει οτιδήποτε, ώστε να την ελέγξεις
με το μάτι πριν προχωρήσεις.

Διαφορά από το pair_pdfs_with_json.py: εκείνο ταιριάζει με ΙΔΙΟ ΟΝΟΜΑ ΑΡΧΕΙΟΥ (ένα
JSON ανά PDF, ίδιο basename) — χρήσιμο όταν επεξεργάζεσαι ένα-ένα τιμολόγιο στο
Gemini. Αυτό εδώ ταιριάζει με ΣΕΙΡΑ (ένα JSON array για πολλά PDF μαζί) — χρήσιμο
όταν ανεβάζεις πολλά τιμολόγια στο Gemini με μία κίνηση και σου γυρνάει ένα
combined array. Χρησιμοποίησε όποιο ταιριάζει με το πώς δουλεύεις πραγματικά.

Πολυσέλιδα τιμολόγια: αν το πλήθος PDF δεν ταιριάζει με το πλήθος τιμολογίων του
JSON, το script ρωτάει πόσες σελίδες έχει κάθε τιμολόγιο (με τη σειρά) — καμία
μαντεψιά βάσει ονόματος αρχείου (τα ADF scans δεν έχουν ειδική ονομασία για
πολυσέλιδα). Το source_pdf_path γίνεται λίστα διαδοχικών PDF όταν ένα τιμολόγιο
έχει πάνω από 1 σελίδα.

Χρήση:
    python pair_pdfs_by_order.py <φάκελος_με_PDF> <gemini_response.json> [--out combined_import.json]
"""
import argparse
import json
import os
import re
import sys

_CITE_RE = re.compile(r'\[cite:\s*[0-9,\s]+\]')


def load_gemini_json(path):
    """Καθαρίζει γνωστές παραξενιές στην ωμή απάντηση του Gemini πριν το json.load:
    inline citation markers όπως "[cite: 4]" που μπερδεύονται ΜΕΣΑ σε πεδία (ΑΦΜ,
    αριθμό παραστατικού κ.λπ.) όταν το Gemini χρησιμοποιεί grounding/citations, το
    markdown code fence (```json ... ```) γύρω από το array, και τυχόν trailing
    κείμενο μετά το JSON (π.χ. ξεχασμένο κλείσιμο ``` σε αρχείο που αποθηκεύτηκε
    αυτούσιο) -- πριν αυτό έσκαγε με "Extra data" ή περνούσε λάθος ΑΦΜ/αριθμούς
    παραστατικού γεμάτους "[cite: N]" (βλ. TODO/DONE 2026-09-30)."""
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    text = _CITE_RE.sub('', text).strip()
    text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
    return json.JSONDecoder().raw_decode(text)[0]


def main():
    parser = argparse.ArgumentParser(
        description='Συνδυασμός φακέλου PDF + ενός JSON array (Gemini batch response) βάσει σειράς.'
    )
    parser.add_argument('folder', help='Φάκελος με τα PDF τιμολογίων')
    parser.add_argument('gemini_json', help='Το JSON array που επέστρεψε το Gemini (πολλά τιμολόγια μαζί)')
    parser.add_argument('--out', default='combined_import.json',
                         help='Όνομα αρχείου εξόδου μέσα στον φάκελο PDF (default: combined_import.json)')
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f'Δεν βρέθηκε ο φάκελος: {folder}')

    # Φυσική ταξινόμηση (1, 2, … 10), όχι αλφαβητική (1, 10, 2, …): τα ονόματα ξεκινούν
    # με αριθμό σειράς σάρωσης και η αλφαβητική έβαζε το «10 …» πριν το «2 …».
    pdfs = sorted(
        (f for f in os.listdir(folder) if f.lower().endswith('.pdf')),
        key=lambda f: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', f)],
    )
    if not pdfs:
        sys.exit(f'Δεν βρέθηκαν PDF μέσα στο: {folder}')

    rows = load_gemini_json(args.gemini_json)
    if not isinstance(rows, list):
        rows = [rows]

    if len(pdfs) == len(rows):
        groups = [[name] for name in pdfs]
    else:
        # Διαφορετικό πλήθος -- πιθανώς κάποια τιμολόγια έχουν πάνω από 1 σελίδα
        # (π.χ. ADF scanner, διαδοχική αρίθμηση, χωρίς ξεχωριστή ονομασία για
        # πολυσέλιδα — βλ. TODO.md). Ρωτάμε τον χειριστή αντί να μαντέψουμε: αυτός
        # ξέρει ποιο τιμολόγιο είχε πόσες σελίδες, όχι το script.
        print(f'{len(pdfs)} PDF στον φάκελο, {len(rows)} τιμολόγια μέσα στο JSON — διαφορετικό πλήθος.')
        print('\nPDF στον φάκελο (αλφαβητικά):')
        for name in pdfs:
            print(f'  - {name}')
        print(f'\n{len(rows)} τιμολόγια στο JSON, με τη σειρά:')
        for i, row in enumerate(rows, 1):
            print(f'  {i}. {row.get("supplier_name") or "?"} | {row.get("doc_date") or "?"}')
        raw = input(
            f'\nΑν κάποια τιμολόγια έχουν πάνω από 1 σελίδα, δώσε πόσες σελίδες έχει το καθένα, '
            f'με τη σειρά, χωρισμένες με κόμμα (π.χ. "1,2,1,1,3" για {len(rows)} τιμολόγια όπου '
            f'το 2ο έχει 2 σελίδες) — Enter για ακύρωση: '
        ).strip()
        if not raw:
            sys.exit('Ακυρώθηκε — δεν γράφτηκε τίποτα.')
        try:
            group_sizes = [int(x) for x in raw.split(',')]
        except ValueError:
            sys.exit('Μη έγκυρη λίστα — περίμενε ακέραιους χωρισμένους με κόμμα.')
        if len(group_sizes) != len(rows):
            sys.exit(f'Έδωσες {len(group_sizes)} μεγέθη αλλά υπάρχουν {len(rows)} τιμολόγια — δεν γράφεται τίποτα.')
        if sum(group_sizes) != len(pdfs):
            sys.exit(f'Το άθροισμα των σελίδων ({sum(group_sizes)}) δεν ταιριάζει με το πλήθος '
                     f'PDF ({len(pdfs)}) — δεν γράφεται τίποτα.')
        groups = []
        pos = 0
        for size in group_sizes:
            groups.append(pdfs[pos:pos + size])
            pos += size

    print(f'\n{len(pdfs)} PDF <-> {len(rows)} τιμολόγια. Προτεινόμενο ταίριασμα (κατά σειρά):\n')
    for group, row in zip(groups, rows):
        supplier = row.get('supplier_name') or '(χωρίς προμηθευτή)'
        date = row.get('doc_date') or '(χωρίς ημερομηνία)'
        total = row.get('total_amount')
        total_str = f'{total} €' if total is not None else '(χωρίς ποσό)'
        pages = ' + '.join(group)
        print(f'  {pages}\n    -> {supplier} | {date} | {total_str}')

    answer = input('\nΤα ταιριάσματα είναι σωστά; (ναι/όχι): ').strip().lower()
    if answer not in ('ναι', 'nai', 'yes', 'y', 'ν'):
        sys.exit('Ακυρώθηκε — δεν γράφτηκε τίποτα. Έλεγξε τη σειρά ανεβάσματος στο Gemini και ξαναδοκίμασε.')

    combined = []
    for group, row in zip(groups, rows):
        row = dict(row)
        paths = [os.path.join(folder, name) for name in group]
        row['source_pdf_path'] = paths[0] if len(paths) == 1 else paths
        combined.append(row)

    out_path = os.path.join(folder, args.out)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f'\nΈτοιμο: {out_path} ({len(combined)} τιμολόγια συνολικά)')
    print('Φόρτωσέ το στο invoicebook (tab Εισαγωγή -> Επιλογή αρχείου) — ΧΩΡΙΣ το κουμπί '
          '"Επιλογή PDF" (το PDF είναι ήδη μέσα σε κάθε τιμολόγιο του JSON).')


if __name__ == '__main__':
    main()
