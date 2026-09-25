# -*- coding: utf-8 -*-
"""
pair_pdfs_with_json.py — συνδυάζει πολλά μεμονωμένα JSON (ένα ανά τιμολόγιο, output
από AI μέσω του IMPORT_PROMPT του intake-tool) με τα αντίστοιχα PDF τους, βάσει ΙΔΙΟΥ
ονόματος αρχείου (χωρίς κατάληξη) — π.χ. "05-03-25 Ζεϊμπέκης.pdf" +
"05-03-25 Ζεϊμπέκης.json". Παράγει ΕΝΑ combined JSON array έτοιμο για μαζική εισαγωγή
στο invoicebook (tab Εισαγωγή -> Επιλογή αρχείου), με το πεδίο source_pdf_path ήδη
συμπληρωμένο σε κάθε τιμολόγιο ώστε το PDF να συνδεθεί αυτόματα κατά το "Επιβεβαίωση"
(βλ. js/import.js: attach_pdf καλείται αυτόματα αν row.data.source_pdf_path υπάρχει).

ΓΙΑΤΙ ΟΧΙ αυτόματο ταίριασμα από το ίδιο το AI: δοκιμάστηκε να ζητηθεί από το Gemini να
επιστρέψει το πρωτότυπο filename μέσα στο JSON (πεδίο source_pdf_filename) — απέτυχε
επανειλημμένα (πρόσθετε "_2", μετά "_3" σε διαδοχικές δοκιμές στα ΙΔΙΑ αρχεία). Δεν
ήταν θέμα διατύπωσης prompt: η πλατφόρμα του Gemini φαίνεται να αποδίδει δικό της
εσωτερικό όνομα σε κάθε upload, και το μοντέλο ειλικρινά αναφέρει εκείνο, όχι το
πραγματικό αρχείο. Άρα το ταίριασμα ΠΡΕΠΕΙ να ελέγχεται από τον χειριστή, όχι από το AI.

Ροή εργασίας:
  1. Για κάθε PDF τιμολογίου, δίνεις το IMPORT_PROMPT + το PDF στο AI.
  2. Σώζεις την απάντηση JSON στον ΙΔΙΟ φάκελο, με το ΙΔΙΟ όνομα αρχείου με το PDF
     (μόνο η κατάληξη αλλάζει: .pdf -> .json).
  3. Όταν έχεις όλα τα ζευγάρια έτοιμα, τρέχεις αυτό το script πάνω στον φάκελο.
  4. Φορτώνεις το combined_import.json που παράγει μέσα στο invoicebook
     (Εισαγωγή -> Επιλογή αρχείου) — ΧΩΡΙΣ να πατήσεις το κουμπί "Επιλογή PDF"
     (το PDF είναι ήδη μέσα στο JSON, ανά τιμολόγιο).

Κανόνας ταιριάσματος: ΑΥΣΤΗΡΑ ίδιο όνομα αρχείου. Αν λείπει ταίρι (JSON χωρίς PDF ή
PDF χωρίς JSON), το script ΔΕΝ μαντεύει — αναφέρει το πρόβλημα και σταματάει χωρίς να
γράψει τίποτα, ώστε να μην καταλήξει λάθος PDF σε λάθος τιμολόγιο (πραγματικά
οικονομικά δεδομένα, βλ. CLAUDE.md).

Πολυσέλιδα τιμολόγια: το ΙΔΙΟ-όνομα κανόνας παραπάνω δεν αρκεί όταν ένα τιμολόγιο έχει
πάνω από 1 σελίδα/σάρωση (π.χ. ADF scanner — τα αρχεία δεν έχουν ειδική ονομασία για
πολυσέλιδα, βλ. TODO.md). Γι' αυτό: αν ο φάκελος περιέχει ΥΠΟΦΑΚΕΛΟΥΣ αντί για flat
αρχεία, κάθε υποφάκελος αντιμετωπίζεται σαν ΕΝΑ τιμολόγιο — όλα τα .pdf μέσα (σε σειρά
ονόματος) + ΑΚΡΙΒΩΣ ένα .json. Καθαρή σύμβαση χωρίς μαντεψιά σε filename pattern: ο
χειριστής απλά φτιάχνει έναν φάκελο ανά τιμολόγιο στον Explorer όταν ξέρει ότι είναι
πολυσέλιδο. Δεν επηρεάζει το flat-file μονοπάτι παραπάνω όταν δεν υπάρχουν υποφάκελοι.

Χρήση:
    python pair_pdfs_with_json.py <φάκελος> [--out combined_import.json]
"""
import argparse
import json
import os
import sys


def _pair_by_subfolder(folder, subdirs, out_name):
    combined = []
    problems = []
    for d in subdirs:
        dpath = os.path.join(folder, d)
        sub_entries = os.listdir(dpath)
        sub_pdfs = sorted(f for f in sub_entries if f.lower().endswith('.pdf'))
        sub_jsons = [f for f in sub_entries if f.lower().endswith('.json') and f != out_name]
        if not sub_pdfs:
            problems.append(f'"{d}": δεν περιέχει κανένα .pdf')
            continue
        if len(sub_jsons) != 1:
            problems.append(f'"{d}": πρέπει να περιέχει ΑΚΡΙΒΩΣ ένα .json (βρέθηκαν {len(sub_jsons)})')
            continue
        json_path = os.path.join(dpath, sub_jsons[0])
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else [data]
        paths = [os.path.join(dpath, name) for name in sub_pdfs]
        for row in rows:
            row['source_pdf_path'] = paths[0] if len(paths) == 1 else paths
            combined.append(row)
        pages_desc = f'{len(sub_pdfs)} σελίδες' if len(sub_pdfs) > 1 else '1 σελίδα'
        print(f'OK: {d}/ ({pages_desc}, {sub_jsons[0]}) -> {len(rows)} τιμολόγιο/α')

    if problems:
        print('\nΣΦΑΛΜΑ:')
        for p in problems:
            print(f'  - {p}')
        sys.exit('\nΔιόρθωσε τα παραπάνω πριν ξανατρέξεις — δεν γίνεται μάντεμα ταιριασμάτων.')

    if not combined:
        sys.exit(f'Δεν βρέθηκε κανένα έγκυρο τιμολόγιο μέσα στους υποφακέλους του: {folder}')

    out_path = os.path.join(folder, out_name)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f'\nΈτοιμο: {out_path} ({len(combined)} τιμολόγια συνολικά)')
    print('Φόρτωσέ το στο invoicebook (tab Εισαγωγή -> Επιλογή αρχείου) — ΧΩΡΙΣ το κουμπί '
          '"Επιλογή PDF" (το PDF είναι ήδη μέσα σε κάθε τιμολόγιο του JSON).')


def main():
    parser = argparse.ArgumentParser(
        description='Συνδυασμός PDF+JSON ζευγαριών (ίδιο όνομα αρχείου) σε ένα combined JSON για μαζική εισαγωγή στο invoicebook.'
    )
    parser.add_argument('folder', help='Φάκελος με τα ζευγάρια .pdf/.json (ίδιο όνομα, διαφορετική κατάληξη)')
    parser.add_argument('--out', default='combined_import.json',
                         help='Όνομα αρχείου εξόδου μέσα στον ίδιο φάκελο (default: combined_import.json)')
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f'Δεν βρέθηκε ο φάκελος: {folder}')

    entries = os.listdir(folder)
    subdirs = sorted(d for d in entries if os.path.isdir(os.path.join(folder, d)))

    if subdirs:
        _pair_by_subfolder(folder, subdirs, args.out)
        return

    pdfs = {os.path.splitext(f)[0]: f for f in entries if f.lower().endswith('.pdf')}
    jsons = {
        os.path.splitext(f)[0]: f for f in entries
        if f.lower().endswith('.json') and f != args.out
    }

    missing_pdf = sorted(set(jsons) - set(pdfs))
    missing_json = sorted(set(pdfs) - set(jsons))
    if missing_pdf or missing_json:
        if missing_pdf:
            print('ΣΦΑΛΜΑ: JSON χωρίς αντίστοιχο PDF (ίδιο όνομα αρχείου):')
            for name in missing_pdf:
                print(f'  - {jsons[name]}')
        if missing_json:
            print('ΣΦΑΛΜΑ: PDF χωρίς αντίστοιχο JSON (ίδιο όνομα αρχείου):')
            for name in missing_json:
                print(f'  - {pdfs[name]}')
        sys.exit('\nΔιόρθωσε τα παραπάνω (μετονομασία/συμπλήρωση) πριν ξανατρέξεις — δεν γίνεται μάντεμα ταιριασμάτων.')

    if not pdfs:
        sys.exit(f'Δεν βρέθηκαν ζευγάρια .pdf/.json μέσα στο: {folder}')

    combined = []
    for name in sorted(pdfs):
        pdf_path = os.path.join(folder, pdfs[name])
        json_path = os.path.join(folder, jsons[name])
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            row['source_pdf_path'] = pdf_path
            combined.append(row)
        print(f'OK: {jsons[name]} -> {pdfs[name]} ({len(rows)} τιμολόγιο/α)')

    out_path = os.path.join(folder, args.out)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f'\nΈτοιμο: {out_path} ({len(combined)} τιμολόγια συνολικά)')
    print('Φόρτωσέ το στο invoicebook (tab Εισαγωγή -> Επιλογή αρχείου) — ΧΩΡΙΣ το κουμπί '
          '"Επιλογή PDF" (το PDF είναι ήδη μέσα σε κάθε τιμολόγιο του JSON).')


if __name__ == '__main__':
    main()
