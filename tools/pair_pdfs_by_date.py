# -*- coding: utf-8 -*-
"""
pair_pdfs_by_date.py — συνδυάζει έναν φάκελο με PDF τιμολογίων (ονομασμένα
"ΗΗ-ΜΜ-ΧΧ Προμηθευτής.pdf") με ΕΝΑ JSON array (batch response του Gemini), βάσει
ΗΜΕΡΟΜΗΝΙΑΣ (+ προμηθευτή όταν υπάρχουν δύο PDF ίδιας ημερομηνίας) — ΟΧΙ βάσει σειράς.

ΓΙΑΤΙ ΟΧΙ σειρά (βλ. pair_pdfs_by_order.py): δοκιμάστηκε στην πράξη (batch Νοεμβρίου
2013) και το Gemini ΔΕΝ επιστρέφει τα τιμολόγια με τη σειρά ανεβάσματος — πιθανώς με
όποια σειρά ολοκληρώνεται η ανάλυση του καθενός. Παρατηρήθηκε όμως ότι αν ταξινομηθούν
οι εγγραφές του JSON με βάση το δικό τους doc_date, ταιριάζουν τέλεια με τα ΗΗ-ΜΜ-ΧΧ
filenames — άρα η ημερομηνία (που ήδη υπάρχει και στο filename ΚΑΙ στο JSON) είναι πολύ
πιο αξιόπιστο κλειδί ταιριάσματος από τη θέση στη λίστα.

Κανόνας ταιριάσματος:
  1. Από κάθε filename "ΗΗ-ΜΜ-ΧΧ Προμηθευτής.pdf" εξάγεται (ΗΗ, ΜΜ, ΧΧ).
  2. Βρίσκονται οι εγγραφές του JSON με ΙΔΙΟ (ΗΗ, ΜΜ, ΧΧ) στο doc_date.
  3. Αν είναι ακριβώς μία -> ταίριασμα.
  4. Αν είναι παραπάνω από μία (π.χ. δύο τιμολόγια ίδιας μέρας) -> διαλέγεται αυτή που
     ο προμηθευτής της (supplier_name) ταιριάζει καλύτερα με το υπόλοιπο του filename
     (κανονικοποιημένη σύγκριση, χωρίς τόνους/κεφαλαία). Αν δεν ξεχωρίζει καθαρά (π.χ. ο
     ΙΔΙΟΣ προμηθευτής δύο φορές ίδια μέρα — η παύλα "ΗΗ-ΜΜ-ΧΧ-" στο filename ξεχωρίζει
     μόνο τα ονόματα αρχείων μεταξύ τους, όχι τον προμηθευτή στο ίδιο το κείμενο) -> γίνεται
     διαδραστική ερώτηση βάσει ΠΟΣΟΥ (μοναδικό ανά τιμολόγιο, σε αντίθεση με τον
     προμηθευτή) — ανοίγεις το PDF, βλέπεις ποιο σύνολο ταιριάζει, απαντάς.
  5. Filename χωρίς ταίριασμα ημερομηνίας, ή JSON εγγραφές που δεν πήραν PDF -> ΔΕΝ
     γράφεται τίποτα, αναφέρονται όλα τα προβλήματα μαζί.

Ίδιο τελικό βήμα με τα άλλα δύο εργαλεία: τυπώνει τη λίστα ταιριασμάτων για οπτικό
έλεγχο, ρωτάει επιβεβαίωση, και μόνο τότε γράφει combined_import.json με το
source_pdf_path συμπληρωμένο.

Πολυσέλιδα τιμολόγια: αν δύο ή περισσότερα PDF filenames έχουν την ΙΔΙΑ ημερομηνία και
ταιριάζουν στο ΙΔΙΟ (μοναδικό) JSON τιμολόγιο, θεωρούνται σελίδες του ίδιου εγγράφου —
ομαδοποιούνται σε ΜΙΑ combined-εγγραφή με source_pdf_path λίστα, όχι διπλότυπες
εγγραφές.

Χρήση:
    python pair_pdfs_by_date.py <φάκελος_με_PDF> <gemini_response.json> [--out combined_import.json]
"""
import argparse
import json
import os
import re
import sys
import unicodedata


FNAME_RE = re.compile(r'^(\d{2})-(\d{2})-(\d{2})[\s\-]+(.+)$')


def tokens(s):
    s = unicodedata.normalize('NFD', s or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.lower().replace('ς', 'σ')
    return {w for w in re.split(r'[^a-zα-ω0-9]+', s) if len(w) >= 3}


def date_key_from_doc_date(doc_date):
    if not doc_date or len(doc_date) < 10:
        return None
    yyyy, mm, dd = doc_date[0:4], doc_date[5:7], doc_date[8:10]
    return (dd, mm, yyyy[2:4])


def main():
    parser = argparse.ArgumentParser(
        description='Συνδυασμός φακέλου PDF ("ΗΗ-ΜΜ-ΧΧ Προμηθευτής.pdf") + ενός JSON array βάσει ημερομηνίας.'
    )
    parser.add_argument('folder', help='Φάκελος με τα PDF τιμολογίων')
    parser.add_argument('gemini_json', help='Το JSON array που επέστρεψε το Gemini')
    parser.add_argument('--out', default='combined_import.json',
                         help='Όνομα αρχείου εξόδου μέσα στον φάκελο PDF (default: combined_import.json)')
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f'Δεν βρέθηκε ο φάκελος: {folder}')

    pdfs = sorted(f for f in os.listdir(folder) if f.lower().endswith('.pdf'))
    if not pdfs:
        sys.exit(f'Δεν βρέθηκαν PDF μέσα στο: {folder}')

    with open(args.gemini_json, 'r', encoding='utf-8') as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        rows = [rows]

    # Ομαδοποίηση JSON εγγραφών ανά (ΗΗ, ΜΜ, ΧΧ).
    by_date = {}
    unparseable_json = []
    for idx, row in enumerate(rows):
        key = date_key_from_doc_date(row.get('doc_date'))
        if key is None:
            unparseable_json.append(idx)
            continue
        by_date.setdefault(key, []).append(idx)

    matches = {}  # pdf filename -> json index
    problems = []
    used_json_idx = set()
    ambiguous = []  # (name, dd, mm, yy, candidates) — λύνεται μετά, βάσει ποσού

    for name in pdfs:
        stem = os.path.splitext(name)[0]
        m = FNAME_RE.match(stem)
        if not m:
            problems.append(f'"{name}": το όνομα δεν έχει τη μορφή "ΗΗ-ΜΜ-ΧΧ Προμηθευτής.pdf"')
            continue
        dd, mm, yy, supplier_part = m.groups()
        candidates = by_date.get((dd, mm, yy), [])
        if not candidates:
            problems.append(f'"{name}": καμία εγγραφή JSON με ημερομηνία {dd}-{mm}-{yy}')
            continue
        if len(candidates) == 1:
            matches[name] = candidates[0]
            used_json_idx.add(candidates[0])
            continue
        # Παραπάνω από μία υποψήφια εγγραφή ίδιας ημερομηνίας -> διάκριση με προμηθευτή
        # μέσω επικάλυψης λέξεων (όχι strict substring — π.χ. "Κοντογούρης Σπυρίδων"
        # vs "ΚΟΝΤΟΓΟΥΡΗΣ Ε. ΣΠΥΡΙΔΩΝ" δεν είναι το ένα substring του άλλου, αλλά
        # μοιράζονται τις δύο σημαντικές λέξεις).
        fname_tokens = tokens(supplier_part)
        scored = [(idx, len(fname_tokens & tokens(rows[idx].get('supplier_name')))) for idx in candidates]
        best_score = max(score for _, score in scored)
        best = [idx for idx, score in scored if score == best_score]
        if best_score > 0 and len(best) == 1:
            matches[name] = best[0]
            used_json_idx.add(best[0])
        else:
            ambiguous.append((name, dd, mm, yy, candidates))

    # Ασαφή ταιριάσματα (π.χ. ο ΙΔΙΟΣ προμηθευτής δύο φορές ίδια μέρα — το filename
    # "ΗΗ-ΜΜ-ΧΧ-" vs "ΗΗ-ΜΜ-ΧΧ" τα ξεχωρίζει μεταξύ τους σαν αρχεία, αλλά και τα δύο
    # καταλήγουν στο ίδιο supplier_part μετά την αφαίρεση ημερομηνίας/παύλας, οπότε ο
    # έλεγχος λέξεων παραπάνω βγάζει ισοπαλία). Το ποσό ΕΙΝΑΙ μοναδικό ανά τιμολόγιο —
    # ρωτάμε τον χειριστή να το διασταυρώσει ανοίγοντας το PDF, αντί να αποτυγχάνουμε.
    if ambiguous:
        print('Ασαφή ταιριάσματα (ίδια ημερομηνία, δεν ξεχωρίζει ο προμηθευτής) — άνοιξε κάθε PDF '
              'και επίλεξε ποιο JSON τιμολόγιο του αντιστοιχεί βάσει ποσού:\n')
        for name, dd, mm, yy, candidates in ambiguous:
            remaining = [i for i in candidates if i not in used_json_idx]
            if not remaining:
                problems.append(
                    f'"{name}": όλες οι υποψήφιες εγγραφές JSON στις {dd}-{mm}-{yy} '
                    f'χρησιμοποιήθηκαν ήδη από άλλο αρχείο'
                )
                continue
            if len(remaining) == 1:
                matches[name] = remaining[0]
                used_json_idx.add(remaining[0])
                continue
            print(f'"{name}" ({dd}-{mm}-{yy}):')
            for n, idx in enumerate(remaining, 1):
                total = rows[idx].get('total_amount')
                total_str = f'{total} €' if total is not None else '(χωρίς ποσό)'
                print(f'    {n}. JSON εγγραφή #{idx + 1} — {rows[idx].get("supplier_name") or "?"} — {total_str}')
            choice = input(f'  Ποιο ταιριάζει στο "{name}"; (1-{len(remaining)}, Enter για παράλειψη): ').strip()
            if choice.isdigit() and 1 <= int(choice) <= len(remaining):
                picked = remaining[int(choice) - 1]
                matches[name] = picked
                used_json_idx.add(picked)
            else:
                problems.append(
                    f'"{name}": {len(candidates)} εγγραφές JSON στις {dd}-{mm}-{yy}, παραλείφθηκε η επιλογή'
                )
            print()

    unmatched_json = [i for i in range(len(rows)) if i not in used_json_idx and i not in unparseable_json
                       and date_key_from_doc_date(rows[i].get('doc_date')) is not None]
    # Ξαναφιλτράρουμε: unmatched_json μόνο για εγγραφές που ΕΙΧΑΝ candidates αλλά δεν πήραν PDF.
    unmatched_json = [i for i in unmatched_json if i not in used_json_idx]

    if problems or unparseable_json or unmatched_json:
        print('ΣΦΑΛΜΑ: δεν γίνεται ασφαλές ταίριασμα — δεν γράφεται τίποτα.\n')
        for p in problems:
            print(f'  - {p}')
        for idx in unparseable_json:
            print(f'  - JSON εγγραφή #{idx + 1} ({rows[idx].get("supplier_name")}): άκυρη/κενή doc_date')
        for idx in unmatched_json:
            print(f'  - JSON εγγραφή #{idx + 1} ({rows[idx].get("supplier_name")}, {rows[idx].get("doc_date")}): '
                  f'δεν βρέθηκε PDF με αυτή την ημερομηνία')
        sys.exit(1)

    # Ομαδοποίηση ανά JSON index: πάνω από ένα filename στο ίδιο idx σημαίνει πολλές
    # σελίδες/σαρώσεις ΤΟΥ ΙΔΙΟΥ τιμολογίου (ίδια ημερομηνία -> μοναδικό candidate ->
    # matched ανεξάρτητα το καθένα από το "if len(candidates) == 1" παραπάνω) — όχι
    # διπλότυπο τιμολόγιο. Πριν αυτή την αλλαγή, κάθε filename έβγαζε ΔΙΚΗ ΤΟΥ
    # combined-εγγραφή (ίδια items, διαφορετικό source_pdf_path) -- σιωπηλό διπλό
    # import αν ξανατρέξεις τον χειριστή/AI πάνω σε πολυσέλιδο. Σημείωση: το ήδη
    # υπάρχον ambiguous-resolution branch (παραπάνω) εξακολουθεί να υποθέτει 1
    # filename <-> 1 ΔΙΑΦΟΡΕΤΙΚΟ idx (σκόπιμα, ξεχωρίζει ΑΝΑΜΕΣΑ σε τιμολόγια) — αν
    # ένα πολυσέλιδο τιμολόγιο συγκρούεται σε ημερομηνία ΚΑΙ με άλλο, διαφορετικό
    # τιμολόγιο ταυτόχρονα, χρειάζεται χειροκίνητη διόρθωση στο combined_import.json.
    names_by_idx = {}
    for name in pdfs:
        names_by_idx.setdefault(matches[name], []).append(name)

    print(f'{len(pdfs)} PDF <-> {len(rows)} τιμολόγια. Ταίριασμα βάσει ημερομηνίας:\n')
    for idx, names in names_by_idx.items():
        row = rows[idx]
        total = row.get('total_amount')
        total_str = f'{total} €' if total is not None else '(χωρίς ποσό)'
        pages = ' + '.join(sorted(names))
        print(f'  {pages}\n    -> {row.get("supplier_name") or "?"} | {row.get("doc_date") or "?"} | {total_str}')

    answer = input('\nΤα ταιριάσματα είναι σωστά; (ναι/όχι): ').strip().lower()
    if answer not in ('ναι', 'nai', 'yes', 'y', 'ν'):
        sys.exit('Ακυρώθηκε — δεν γράφτηκε τίποτα.')

    combined = []
    for idx, names in names_by_idx.items():
        row = dict(rows[idx])
        paths = [os.path.join(folder, name) for name in sorted(names)]
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
