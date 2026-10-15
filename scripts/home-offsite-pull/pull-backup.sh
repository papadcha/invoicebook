#!/bin/sh
# pull-backup.sh — τράβηγμα του backup του InvoiceBook στο UGREEN του σπιτιού (POSIX sh / busybox ash).
# Τρέχει ΜΕΣΑ στο container rclone/rclone (βλ. docker-compose.pull.yml και README.md).
#
# Ασφάλεια (ΜΗΝ το χαλάσεις):
#  - ΜΟΝΟ ΑΝΤΙΓΡΑΦΗ προς το σπίτι: `rclone copy` για τη βάση και το pdf_store (ποτέ διαγραφή στο σπίτι).
#  - Μόνη εξαίρεση ο φάκελος pdf_store_archives (τα εβδομαδιαία zip των 2 GB, η πηγή κρατά 4): `rclone sync`
#    με --max-delete, ώστε να μη μαζεύονται όλα, αλλά και να μη σβηστεί τίποτα αν η πηγή φανεί λάθος/άδεια.
#  - Πριν από ΟΤΙΔΗΠΟΤΕ ελέγχει ότι η πηγή διαβάζεται και δεν είναι άδεια — αλλιώς σταματά χωρίς να αγγίξει τίποτα.
#  - Η πηγή διαβάζεται μόνο· ο χρήστης στο Synology πρέπει να έχει δικαίωμα ΑΝΑΓΝΩΣΗΣ μόνο.
#
# Ρυθμίσεις με μεταβλητές περιβάλλοντος (όλες προαιρετικές — βλ. docker-compose.pull.yml):
#   SRC_REMOTE   remote του rclone με «:» στο τέλος (προεπιλογή «synology:», δρόμος Β μέσω Tailscale·
#                για δρόμο Α από cloud βάλε «pcloud:» ή «mega:» και SRC_PATH=invoicebook-backup)
#   SRC_PATH     φάκελος backup στην πηγή (προεπιλογή /volume1/ds218/Projects/Invoicebook/backup)
#   DST_DIR      προορισμός στο UGREEN (προεπιλογή /data/invoicebook-backup)
#   STATUS_DIR   φάκελος κατάστασης/log (προεπιλογή /data/_status)
#   BWLIMIT      όριο ταχύτητας rclone, π.χ. 8M (προεπιλογή: κανένα)
#   MAX_ARCHIVE_DELETES  μέγιστα zip που επιτρέπεται να σβηστούν ανά εκτέλεση (προεπιλογή 2· η κανονική περιστροφή σβήνει 1/εβδομάδα)

set -u

SRC_REMOTE="${SRC_REMOTE-synology:}"   # «-» (όχι «:-»): κενό = τοπική διαδρομή (για δοκιμές)
SRC_PATH="${SRC_PATH:-/volume1/ds218/Projects/Invoicebook/backup}"
DST_DIR="${DST_DIR:-/data/invoicebook-backup}"
STATUS_DIR="${STATUS_DIR:-/data/_status}"
LOG="${LOG_FILE:-$STATUS_DIR/pull.log}"
BWLIMIT="${BWLIMIT:-}"
MAX_ARCHIVE_DELETES="${MAX_ARCHIVE_DELETES:-2}"
RCLONE="${RCLONE_BIN:-rclone}"
SRC="${SRC_REMOTE}${SRC_PATH}"

mkdir -p "$DST_DIR/pdf_store" "$DST_DIR/pdf_store_archives" "$STATUS_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) $*" | tee -a "$LOG"; }

COMMON="--transfers 2 --checkers 4 --retries 3 --low-level-retries 10 --timeout 5m --contimeout 30s --log-level INFO --stats-one-line --stats 5m"
if [ -n "$BWLIMIT" ]; then COMMON="$COMMON --bwlimit $BWLIMIT"; fi

START=$(date +%s)
log "=== Έναρξη: $SRC  ->  $DST_DIR"

# 1) Φρουρός: η πηγή πρέπει να διαβάζεται ΚΑΙ να μην είναι άδεια.
LISTING="$STATUS_DIR/src-listing.tmp"
if ! $RCLONE lsf "$SRC" --max-depth 1 --log-level ERROR > "$LISTING" 2>>"$LOG"; then
  log "ΣΦΑΛΜΑ: δεν διαβάζεται η πηγή ($SRC) — διακοπή, δεν αγγίχτηκε τίποτα"
  echo "$(ts) FAIL source-unreadable" > "$STATUS_DIR/last-run.txt"
  exit 2
fi
if [ ! -s "$LISTING" ]; then
  log "ΣΦΑΛΜΑ: η πηγή ($SRC) είναι ΑΔΕΙΑ — διακοπή (προστασία από σβήσιμο)"
  echo "$(ts) FAIL source-empty" > "$STATUS_DIR/last-run.txt"
  exit 3
fi

RC=0
run() {
  log "→ $*"
  if ! "$@" >>"$LOG" 2>&1; then
    log "ΣΦΑΛΜΑ: $*"
    RC=1
  fi
}

# 2) Snapshots βάσης (αρχεία στη ρίζα, όχι οι υποφάκελοι) — μόνο αντιγραφή
run $RCLONE copy "$SRC" "$DST_DIR" --max-depth 1 $COMMON

# 3) Προσθετικό mirror των PDF — μόνο αντιγραφή (ποτέ διαγραφή)
if grep -q '^pdf_store/$' "$LISTING"; then
  run $RCLONE copy "$SRC/pdf_store" "$DST_DIR/pdf_store" $COMMON
else
  log "ΠΑΡΑΤΗΡΗΣΗ: δεν υπάρχει pdf_store στην πηγή — παραλείπεται"
fi

# 4) Εβδομαδιαία zip: sync με όριο διαγραφών (η πηγή κρατά 4). Φρουρός: αν η πηγή δεν έχει ΚΑΝΕΝΑ zip, ΔΕΝ γίνεται
#    sync (θα έσβηνε τα αντίγραφα του σπιτιού)· δηλώνεται ως σφάλμα για να φανεί.
if grep -q '^pdf_store_archives/$' "$LISTING"; then
  ZIPS=$($RCLONE lsf "$SRC/pdf_store_archives" --files-only --max-depth 1 --log-level ERROR 2>>"$LOG" | grep -c '\.zip$')
  if [ "${ZIPS:-0}" -ge 1 ]; then
    run $RCLONE sync "$SRC/pdf_store_archives" "$DST_DIR/pdf_store_archives" --max-delete "$MAX_ARCHIVE_DELETES" $COMMON
  else
    log "ΠΡΟΣΟΧΗ: ο φάκελος pdf_store_archives στην πηγή δεν έχει κανένα zip — ΔΕΝ γίνεται sync (προστασία των zip του σπιτιού)"
    RC=1
  fi
else
  log "ΠΑΡΑΤΗΡΗΣΗ: δεν υπάρχει pdf_store_archives στην πηγή — παραλείπεται"
fi

END=$(date +%s)
SECS=$((END - START))
if [ "$RC" -eq 0 ]; then
  log "=== ΕΠΙΤΥΧΙΑ σε ${SECS}s"
  echo "$(ts) OK ${SECS}s" > "$STATUS_DIR/last-run.txt"
  echo "$(ts)" > "$STATUS_DIR/last-ok.txt"
else
  log "=== ΤΕΛΕΙΩΣΕ ΜΕ ΣΦΑΛΜΑΤΑ σε ${SECS}s — δες το $LOG"
  echo "$(ts) FAIL errors ${SECS}s" > "$STATUS_DIR/last-run.txt"
fi
exit "$RC"
