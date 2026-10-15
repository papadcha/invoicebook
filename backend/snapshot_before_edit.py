# -*- coding: utf-8 -*-
"""
snapshot_before_edit.py — αντίγραφο ασφαλείας του invoicebook.db πριν από ένα
χειροκίνητο edit (π.χ. μέσα σε συνομιλία με Claude Code), με αυτόματο pruning.

Χρήση:
    python backend/snapshot_before_edit.py "σύντομη-περιγραφή-edit"

Ποια βάση: η πραγματική είναι στον εξωτερικό δίσκο (`<γράμμα>:\\InvoiceBookData\\invoicebook.db`,
βλ. scripts/launch-portable.ps1), ΟΧΙ στο backend/ (το backend/invoicebook.db διαγράφηκε
2026-10-15, ήταν άδειο και μπέρδευε). Σειρά αναζήτησης: μεταβλητή `INVOICES_DB_PATH`
(όπως η εφαρμογή) → σάρωση γραμμάτων δίσκου για `InvoiceBookData\\invoicebook.db`· αν βρεθούν
0 ή >1, σταματά με μήνυμα αντί να μαντέψει. Το αντίγραφο γράφεται εδώ στο backend/.

Αντικαθιστά το προηγούμενο ad-hoc `cp invoicebook.db invoicebook.db.bak-<περιγραφή>-<ts>`
(καμία σχέση με το backup_config.json/backup.py του intake-tool — αυτό εδώ είναι μόνο
για πρόχειρα ενδοσυνεδριακά snapshots πριν από ρίσκο, όχι μόνιμο backup) -- ίδιο readable
όνομα/timestamp, αλλά ΜΕ αυτόματο keep-last-N pruning ώστε να μη συσσωρεύεται επ' αόριστον
(βλ. TODO.md: 116 αρχεία/784MB καθαρίστηκαν χειροκίνητα μια φορά, 2026-09-13 -- αυτό
υπάρχει για να μην ξαναχρειαστεί χειροκίνητο καθάρισμα).
"""
import os
import re
import sqlite3
import string
import sys
from datetime import datetime
from pathlib import Path

KEEP = 30  # ~30 edits ιστορικού είναι άφθονο για rollback, αλλά φράζει τη συσσώρευση
HERE = Path(__file__).parent


def find_db() -> Path:
    """Η πραγματική βάση: INVOICES_DB_PATH, αλλιώς η μοναδική `<γράμμα>:\\InvoiceBookData\\invoicebook.db`."""
    env = os.environ.get('INVOICES_DB_PATH')
    if env:
        return Path(env)
    found = [Path(f'{d}:\\InvoiceBookData\\invoicebook.db') for d in string.ascii_uppercase
             if Path(f'{d}:\\InvoiceBookData\\invoicebook.db').is_file()]
    if len(found) != 1:
        raise FileNotFoundError(
            'Δεν βρέθηκε μία μοναδική βάση <γράμμα>:\\InvoiceBookData\\invoicebook.db '
            f'(βρέθηκαν {len(found)}). Ορίστε INVOICES_DB_PATH. Είναι συνδεδεμένος ο εξωτερικός δίσκος;')
    return found[0]


def snapshot(reason: str, db_path: Path) -> Path:
    reason = re.sub(r'[^A-Za-z0-9_-]', '-', reason.strip())[:60] or 'edit'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = HERE / f'invoicebook.db.bak-{reason}-{ts}'
    # backup API αντί για copy: συνεπές αντίγραφο ακόμα κι αν η εφαρμογή είναι ανοιχτή
    src = sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    backups = sorted(HERE.glob('invoicebook.db.bak-*'), key=lambda p: p.stat().st_mtime)
    for old in backups[:-KEEP]:
        old.unlink()

    return dest


if __name__ == '__main__':
    try:
        db = find_db()
        if not db.is_file():
            raise FileNotFoundError(f'invoicebook.db δεν βρέθηκε: {db}')
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    reason = sys.argv[1] if len(sys.argv) > 1 else 'edit'
    print(f'Βάση: {db}')
    print(f'Snapshot: {snapshot(reason, db)}')
