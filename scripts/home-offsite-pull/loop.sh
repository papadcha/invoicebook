#!/bin/sh
# loop.sh — εκτελεί το pull-backup.sh μία φορά τη νύχτα (και προαιρετικά στην εκκίνηση του container).
# Το rclone/rclone image είναι Alpine/busybox: δεν έχει cron και το `date -d` είναι περιορισμένο, γι' αυτό
# ελέγχουμε κάθε 10 λεπτά αν είναι η ώρα εκτέλεσης και αν δεν έχει ήδη τρέξει σήμερα.
#   RUN_HOUR      ώρα εκτέλεσης «HH» (προεπιλογή 03)
#   RUN_ON_START  1 = τρέξε και αμέσως στην εκκίνηση (προεπιλογή 1)
#   TZ            ζώνη ώρας· το image δεν έχει tzdata, βάλε POSIX μορφή: EET-2EEST,M3.5.0/3,M10.5.0/4 (Ελλάδα)

RUN_HOUR="${RUN_HOUR:-03}"
RUN_ON_START="${RUN_ON_START:-1}"
STATUS_DIR="${STATUS_DIR:-/data/_status}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/scripts}"
mkdir -p "$STATUS_DIR"
LAST="$STATUS_DIR/last-loop-day"

if [ "$RUN_ON_START" = "1" ]; then
  sh "$SCRIPTS_DIR/pull-backup.sh"
  date +%F > "$LAST"
fi

while true; do
  H=$(date +%H)
  D=$(date +%F)
  if [ "$H" = "$RUN_HOUR" ] && [ "$(cat "$LAST" 2>/dev/null)" != "$D" ]; then
    sh "$SCRIPTS_DIR/pull-backup.sh"
    date +%F > "$LAST"
  fi
  sleep 600
done
