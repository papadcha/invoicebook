# -*- coding: utf-8 -*-
"""
snapshot_before_edit.py — αντίγραφο ασφαλείας του invoicebook.db πριν από ένα
χειροκίνητο edit (π.χ. μέσα σε συνομιλία με Claude Code), με αυτόματο pruning.

Χρήση:
    python backend/snapshot_before_edit.py "σύντομη-περιγραφή-edit"

Αντικαθιστά το προηγούμενο ad-hoc `cp invoicebook.db invoicebook.db.bak-<περιγραφή>-<ts>`
(καμία σχέση με το backup_config.json/backup.py του intake-tool — αυτό εδώ είναι μόνο
για πρόχειρα ενδοσυνεδριακά snapshots πριν από ρίσκο, όχι μόνιμο backup) -- ίδιο readable
όνομα/timestamp, αλλά ΜΕ αυτόματο keep-last-N pruning ώστε να μη συσσωρεύεται επ' αόριστον
(βλ. TODO.md: 116 αρχεία/784MB καθαρίστηκαν χειροκίνητα μια φορά, 2026-09-13 -- αυτό
υπάρχει για να μην ξαναχρειαστεί χειροκίνητο καθάρισμα).
"""
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

KEEP = 30  # ~30 edits ιστορικού είναι άφθονο για rollback, αλλά φράζει τη συσσώρευση
HERE = Path(__file__).parent
DB_PATH = HERE / 'invoicebook.db'


def snapshot(reason: str) -> Path:
    reason = re.sub(r'[^A-Za-z0-9_-]', '-', reason.strip())[:60] or 'edit'
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = HERE / f'invoicebook.db.bak-{reason}-{ts}'
    shutil.copy2(DB_PATH, dest)

    backups = sorted(HERE.glob('invoicebook.db.bak-*'), key=lambda p: p.stat().st_mtime)
    for old in backups[:-KEEP]:
        old.unlink()

    return dest


if __name__ == '__main__':
    if not DB_PATH.exists():
        print(f'invoicebook.db δεν βρέθηκε: {DB_PATH}', file=sys.stderr)
        sys.exit(1)
    reason = sys.argv[1] if len(sys.argv) > 1 else 'edit'
    print(f'Snapshot: {snapshot(reason)}')
