#!/bin/sh
# check-backup.sh — επαλήθευση του αντιγράφου στο UGREEN (POSIX sh). Τρέξ' το χειροκίνητα ή εβδομαδιαία:
#   docker exec invoicebook-pull sh /scripts/check-backup.sh
# Ελέγχει: (1) ότι ό,τι υπάρχει στην πηγή υπάρχει και στο σπίτι (rclone check --one-way, μέγεθος),
# (2) την ηλικία του τελευταίου snapshot βάσης, (3) τον ελεύθερο χώρο, (4) αν υπάρχει sqlite3, την ακεραιότητα
# του τελευταίου snapshot. Εξοδος 0 = όλα καλά, 1 = κάτι θέλει προσοχή.
# Δεν αντικαθιστά τη ΜΗΝΙΑΙΑ δοκιμή επαναφοράς (README, ενότητα «Επαλήθευση»).

set -u
SRC_REMOTE="${SRC_REMOTE-synology:}"   # «-» (όχι «:-»): κενό = τοπική διαδρομή (για δοκιμές)
SRC_PATH="${SRC_PATH:-/volume1/ds218/Projects/Invoicebook/backup}"
DST_DIR="${DST_DIR:-/data/invoicebook-backup}"
MAX_AGE_DAYS="${MAX_AGE_DAYS:-3}"
RCLONE="${RCLONE_BIN:-rclone}"
SRC="${SRC_REMOTE}${SRC_PATH}"
PROBLEMS=0

say() { echo "$*"; }
bad() { echo "ΠΡΟΣΟΧΗ: $*"; PROBLEMS=1; }

say "== 1) Η πηγή υπάρχει και στο σπίτι (μόνο μέγεθος) =="
$RCLONE check "$SRC" "$DST_DIR" --one-way --size-only --max-depth 1 --log-level ERROR 2>&1 || bad "λείπουν/διαφέρουν snapshots βάσης"
$RCLONE check "$SRC/pdf_store" "$DST_DIR/pdf_store" --one-way --size-only --log-level ERROR 2>&1 || bad "λείπουν/διαφέρουν PDF στο mirror"
$RCLONE check "$SRC/pdf_store_archives" "$DST_DIR/pdf_store_archives" --one-way --size-only --log-level ERROR 2>&1 || bad "λείπουν/διαφέρουν zip PDF"

say "== 2) Τελευταίο snapshot βάσης =="
LATEST=$(ls -1 "$DST_DIR"/invoicebook_backup_* 2>/dev/null | sort | tail -1)
if [ -z "$LATEST" ]; then
  bad "δεν βρέθηκε κανένα snapshot βάσης στο $DST_DIR"
else
  AGE=$(( ( $(date +%s) - $(stat -c %Y "$LATEST") ) / 86400 ))
  say "   $LATEST  (ηλικία $AGE ημέρες)"
  if [ "$AGE" -gt "$MAX_AGE_DAYS" ]; then bad "το τελευταίο snapshot είναι παλιότερο από $MAX_AGE_DAYS ημέρες (έγινε backup στο γραφείο; τρέχει το pull;)"; fi
fi

say "== 3) Χώρος =="
df -h "$DST_DIR" 2>/dev/null | tail -1

say "== 4) Ακεραιότητα τελευταίου snapshot =="
if [ -n "${LATEST:-}" ] && command -v sqlite3 >/dev/null 2>&1; then
  TMP="/tmp/integrity-check.db"
  case "$LATEST" in
    *.gz) gunzip -c "$LATEST" > "$TMP" ;;
    *)    cp "$LATEST" "$TMP" ;;
  esac
  RES=$(sqlite3 "$TMP" 'PRAGMA integrity_check;' 2>&1 | head -1)
  say "   PRAGMA integrity_check: $RES"
  [ "$RES" = "ok" ] || bad "η ακεραιότητα του snapshot ΔΕΝ είναι ok"
  rm -f "$TMP"
else
  say "   (παραλείπεται: δεν υπάρχει sqlite3 στο container — κάνε τη μηνιαία δοκιμή επαναφοράς από υπολογιστή, README)"
fi

if [ "$PROBLEMS" -eq 0 ]; then say "== ΟΛΑ ΚΑΛΑ =="; else say "== ΥΠΑΡΧΟΥΝ ΠΡΟΒΛΗΜΑΤΑ (δες παραπάνω) =="; fi
exit "$PROBLEMS"
