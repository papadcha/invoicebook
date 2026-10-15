# Backup του InvoiceBook στο σπίτι (UGREEN DXP2800) — οδηγός στήσιμου

**Τι κάνει:** το UGREEN στο σπίτι «τραβάει» το backup που ήδη γράφει η εφαρμογή (στο Synology `Z:` ή στα cloud)
και το κρατά σε δικό του δίσκο, μία φορά τη νύχτα. **Δεν αλλάζει τίποτα στην εφαρμογή ή στο Synology.**
Σχέδιο και αποφάσεις: `TODO.md`, ενότητα «Backup στο σπίτι (UGREEN DXP2800)».

```
 Υπολογιστής ──(backup στο κλείσιμο)──► Synology DS218 (Z:)  ──► pCloud / Mega
                                              │  Tailscale (δρόμος Β)        │  (δρόμος Α)
                                              └──────────► UGREEN στο σπίτι ◄┘   «τραβάει» μία φορά τη νύχτα
```

## Ασφάλεια — διάβασέ το πρώτο
- **Μόνο αντιγραφή προς το σπίτι.** Το `pull-backup.sh` ΔΕΝ σβήνει ποτέ τίποτα στο σπίτι, εκτός από τον φάκελο των εβδομαδιαίων zip
  (η πηγή κρατά 4· εκεί γίνεται `sync`, και μόνο αν η πηγή έχει zip και έως 2 διαγραφές ανά εκτέλεση).
- **Φρουροί:** αν η πηγή δεν διαβάζεται ή είναι άδεια, το script σταματά χωρίς να αγγίξει τίποτα.
- **Κωδικοί:** το **Tailscale auth key**, το **`rclone.conf`** και το **ssh key** ζουν ΜΟΝΟ στο UGREEN. Δεν μπαίνουν στο git
  (το `.gitignore` τα αποκλείει), δεν στέλνονται σε mail ή στον Claude. Ο χρήστης στο Synology να έχει δικαίωμα **ανάγνωσης μόνο**.
- **Snapshots στο UGREEN** (βήμα 7): ό,τι κι αν πάει στραβά στο αντίγραφο, γυρίζεις στο χθεσινό.

## Δύο δρόμοι (η ίδια υπόλοιπη εγκατάσταση)
| | Πηγή | Χρειάζεται |
|---|---|---|
| **Β (προτείνεται)** | Synology `Z:` μέσω Tailscale (SFTP) | Tailscale στο UGREEN, SFTP/SSH στο Synology |
| **Α (εφεδρικός)** | pCloud ή Mega | μόνο το `rclone.conf` με το remote του cloud |

Το Synology έχει ήδη Tailscale (λογαριασμός `latomeiagalatistas`). Μπορείς να κάνεις πρώτα τον Α (δουλεύει χωρίς Tailscale) και μετά τον Β.

## Βήμα 1 — Tailscale στο UGREEN (μόνο για τον δρόμο Β)
1. UGOS → **App Center** → εγκατάσταση **Docker**.
2. Φτιάξε τον φάκελο `/volume1/docker/tailscale/state`.
3. Tailscale admin console (login.tailscale.com, λογαριασμός `latomeiagalatistas`) → **Settings → Keys → Generate auth key**. Αντίγραψέ το αμέσως (φαίνεται μία φορά).
4. UGOS → **Docker → Project → Create** → επικόλλησε το `docker-compose.tailscale.yml`, βάλε το key στη θέση του placeholder → **Deploy**.
5. Στο admin console βρες τη συσκευή `ugreen-nas` και **απενεργοποίησε το key expiry** (αλλιώς σταματά σιωπηλά κάθε ~180 ημέρες).
6. Δοκιμή: `docker exec tailscale tailscale status` — πρέπει να δεις και το Synology.
   `docker exec tailscale tailscale ping 100.X.Y.Z` — δείχνει αν η σύνδεση είναι **άμεση** (καλό) ή μέσω relay (αργή για τα 8–15 GB της πρώτης μεταφοράς).

## Βήμα 2 — Synology (μόνο για τον δρόμο Β)
1. Πίνακας Ελέγχου → **Υπηρεσίες αρχείων → FTP → ενεργοποίηση SFTP** (ή Τερματικό και SNMP → ενεργοποίηση SSH).
2. Φτιάξε χρήστη `pull-backup` με δικαίωμα **ανάγνωσης μόνο** στο κοινόχρηστο `ds218` (φάκελος `Projects`).
3. Κλειδί: στο UGREEN `ssh-keygen -t ed25519 -f /volume1/docker/invoicebook-pull/config/id_ed25519 -N ""`, και βάλε το δημόσιο κλειδί (`.pub`)
   στο `~/.ssh/authorized_keys` του χρήστη στο Synology (το DSM θέλει home service ενεργό και δικαιώματα 700 στο `.ssh`, 600 στο `authorized_keys`).
4. Διεύθυνση Tailscale του Synology: `sudo tailscale status` ή το admin console (μορφή `100.x.y.z`). **Χρησιμοποίησε τη διεύθυνση, όχι το όνομα**
   (το UGREEN τρέχει με `--accept-dns=false`, δεν λύνει MagicDNS).

## Βήμα 3 — Φάκελοι στο UGREEN
```
/volume1/backup-invoicebook                      ← προορισμός (κοινόχρηστος φάκελος· εδώ θα μπουν snapshots, βήμα 7)
/volume1/docker/invoicebook-pull/config          ← rclone.conf, id_ed25519
/volume1/docker/invoicebook-pull/scripts         ← pull-backup.sh, loop.sh, check-backup.sh
```
Αντίγραψε στο `scripts/` τα τρία `.sh` από αυτόν τον φάκελο του repo (με `git pull` στο σπίτι).

## Βήμα 4 — `rclone.conf`
Αντίγραψε το `rclone.conf.example` ως `/volume1/docker/invoicebook-pull/config/rclone.conf` και συμπλήρωσε το `host = 100.X.Y.Z`.
Για τον δρόμο Α πρόσθεσε τα remotes `pcloud`/`mega` από το `rclone.conf` του υπολογιστή του γραφείου (με USB ή απευθείας στο UGREEN — **όχι με mail**).

## Βήμα 5 — Deploy του pull
UGOS → Docker → Project → Create → επικόλλησε το `docker-compose.pull.yml` (έλεγξε τις μεταβλητές `SRC_REMOTE`/`SRC_PATH`) → Deploy.
Το container τρέχει αμέσως μία φορά (`RUN_ON_START=1`) και μετά κάθε νύχτα στις 03:00.
Η διαδρομή της πηγής στο Synology είναι συνήθως `/volume1/ds218/Projects/Invoicebook/backup` — **επιβεβαίωσέ την**:
`docker exec invoicebook-pull rclone lsd synology:/` (δες τα κοινόχρηστα) και `rclone lsf synology:/volume1/ds218/Projects/Invoicebook/backup`.

## Βήμα 6 — Πρώτη εκτέλεση και παρακολούθηση
- Πρώτη μεταφορά ~8–15 GB (στα 300 Mbps λήψης, ανάλογα με το upload του χώρου του Synology).
- Παρακολούθηση: `docker logs -f invoicebook-pull` και τα αρχεία στο `/volume1/backup-invoicebook/_status/`:
  `last-run.txt` (OK ή FAIL), `last-ok.txt` (πότε πέτυχε τελευταία φορά), `pull.log`.
- Χειροκίνητη εκτέλεση: `docker exec invoicebook-pull sh /scripts/pull-backup.sh`.

## Βήμα 7 — Snapshots στο UGREEN
Στο UGOS ενεργοποίησε **ημερήσια snapshots** στον φάκελο `backup-invoicebook` (volume Btrfs), κράτα 14–30. Το RAID 1 προστατεύει από χαλασμένο δίσκο,
**όχι** από λάθος ή ransomware — γι' αυτό τα snapshots.

## Βήμα 8 — Επαλήθευση
- **Εβδομαδιαία:** `docker exec invoicebook-pull sh /scripts/check-backup.sh` — ελέγχει ότι ό,τι υπάρχει στην πηγή υπάρχει και στο σπίτι,
  την ηλικία του τελευταίου snapshot βάσης (προειδοποιεί αν >3 ημέρες) και τον χώρο.
- **Μηνιαία δοκιμή επαναφοράς (σημαντικό):** πάρε το τελευταίο `invoicebook_backup_*.db.gz` από το UGREEN, αποσυμπίεσέ το και τρέξε
  `python -c "import sqlite3;c=sqlite3.connect('invoicebook.db');print(c.execute('pragma integrity_check').fetchone())"` — πρέπει να γράψει `('ok',)`.
  Ένα αντίγραφο που δεν έχει δοκιμαστεί να επανέλθει δεν είναι αντίγραφο.

## Προβλήματα
| Σύμπτωμα | Αιτία / λύση |
|---|---|
| `FAIL source-unreadable` | Το UGREEN δεν φτάνει την πηγή: `tailscale ping`, έλεγξε SFTP/κλειδί, ή τη διαδρομή `SRC_PATH` |
| `FAIL source-empty` | Η πηγή είναι άδεια· δεν σβήστηκε τίποτα — έλεγξε αν τρέχει το backup στο γραφείο |
| Το container δεν βλέπει `100.x.y.z` | Το pull πρέπει να έχει `network_mode: host` (όπως το Tailscale) |
| Σταμάτησε μετά ~180 ημέρες | Έληξε το key του Tailscale: απενεργοποίησε το key expiry (βήμα 1.5) |
| Λάθος ώρα εκτέλεσης | Το `TZ` είναι σε POSIX μορφή (το image δεν έχει tzdata) — βλ. `docker-compose.pull.yml` |
| Το script «δεν τρέχει» με `sh\r` | Τα `.sh` πρέπει να έχουν LF (το `.gitattributes` το εξασφαλίζει) |

## Τι δοκιμάστηκε
Τα scripts δοκιμάστηκαν στον υπολογιστή του γραφείου με ψεύτικη πηγή (ίδια διάταξη με το backup): πρώτο τράβηγμα, δεύτερη εκτέλεση (δεν ξανακατεβάζει),
περιστροφή snapshots/zip, άδεια ή ανύπαρκτη πηγή (σταματά), άδειος φάκελος zip (δεν σβήνεται τίποτα), προσθετικότητα (PDF που σβήστηκε στην πηγή μένει στο σπίτι),
`check-backup.sh` και `loop.sh`. **Δεν δοκιμάστηκε** η σύνδεση με το πραγματικό Synology/UGREEN/Tailscale — αυτό γίνεται στο στήσιμο.
