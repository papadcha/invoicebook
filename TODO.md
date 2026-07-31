# TODO

- [ ] Presence detection μέσω MEGA/rclone sync — κάθε client γράφει periodic
      heartbeat (`presence.json`: user, last_seen, computer) στο ίδιο MEGA
      remote που θα χρησιμοποιείται και για DB backup/sync. Sync στην
      εκκίνηση + κάθε 1-2 λεπτά όσο τρέχει η εφαρμογή. UI: "● online" αν
      `last_seen` < 2 λεπτά, αλλιώς "τελευταία σύνδεση: πριν Χ".
      Reference implementation: `modules/cloud-sync.js` στο
      `lab-galatista-v2` worktree (IPC handlers `cloud-test`/`cloud-sync`,
      rclone sync pattern) — ίδιο pattern θα προστεθεί και εδώ.

      **Προαπαιτούμενο:** το invoicebook δεν έχει καθόλου cloud
      backup/sync υποδομή ακόμα (δεν υπάρχει rclone/MEGA integration,
      βλ. `CLAUDE.md` — δεν αναφέρεται πουθενά). Πρέπει πρώτα να προστεθεί
      το βασικό cloud-sync module (κατά το πρότυπο lab-galatista/expvault)
      πριν μπει το heartcheck/presence πάνω του.
