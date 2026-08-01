# TODO

- [ ] Presence detection μέσω MEGA/rclone sync — κάθε client γράφει periodic
      heartbeat (`presence.json`: user, last_seen, computer) στο ίδιο MEGA
      remote που θα χρησιμοποιείται και για DB backup/sync. Sync στην
      εκκίνηση + κάθε 1-2 λεπτά όσο τρέχει η εφαρμογή. UI: "● online" αν
      `last_seen` < 2 λεπτά, αλλιώς "τελευταία σύνδεση: πριν Χ".

      Ενημέρωση 2026-08-01: υπάρχουν πλέον **δύο** ολοκληρωμένες reference
      υλοποιήσεις να επιλεγεί ανάλογα με το ποια ταιριάζει καλύτερα στην
      αρχιτεκτονική του invoicebook —
      - `expvault` (branch `v2`, `backend/presence.py`): rclone κλήσεις
        μέσα από το Python backend (`send_heartbeat()`/`list_presence()`,
        heartbeat key `<computer>__<user>.json` — όχι μόνο hostname, ώστε
        δύο μηχανήματα με ίδιο default hostname να μην
        αλληλοεπικαλύπτονται). Sidebar UI: πράσινο/κόκκινο status button
        στην κορυφή του sidebar, ακριβώς κάτω από το app icon + έκδοση
        (`#sidebar-presence`, βλ. `DONE-v2.md`'s "Sidebar/titlebar
        redesign" section) — click πλοηγεί στον αναλυτικό πίνακα της
        σελίδας Backup. Νέα bridge εντολή `whoami` ώστε το renderer να
        εξαιρεί το δικό του heartbeat από το "υπάρχει *άλλος* online".
      - `lab-galatista` (`modules/presence.js`): ίδιο pattern αλλά rclone
        κλήσεις απευθείας από το Electron main process (JS), κατά το
        πρότυπο του ήδη υπάρχοντος `modules/cloud-sync.js` εκεί
        (IPC handlers `cloud-test`/`cloud-sync`). Ίδιο sidebar badge
        design (`#sidebar-presence-badge`, πράσινο "Μόνος" / κόκκινο "Χ
        online", click → Ρυθμίσεις).

      Και οι δύο μοιράζονται: ίδιο 2-λεπτο online threshold, ίδιο
      "εξαίρεσε τον εαυτό σου" identity filtering (user+computer, όχι
      μόνο hostname), ίδιο manifest-merge pattern (ένα `rclone copy` όλων
      των heartbeat αρχείων τοπικά, μετά τοπικό JSON merge — όχι
      `lsjson`+per-file fetch).

      **Προαπαιτούμενο:** το invoicebook δεν έχει καθόλου cloud
      backup/sync υποδομή ακόμα (δεν υπάρχει rclone/MEGA integration,
      βλ. `CLAUDE.md` — δεν αναφέρεται πουθενά). Πρέπει πρώτα να προστεθεί
      το βασικό cloud-sync module (κατά το πρότυπο lab-galatista/expvault)
      πριν μπει το heartbeat/presence πάνω του.
