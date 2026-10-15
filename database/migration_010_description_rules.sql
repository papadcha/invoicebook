-- Migration 010 — Κανόνας αντικατάστασης περιγραφών (regex) για τον καθαρισμό περιγραφών + μόνιμοι κανόνες
-- που εφαρμόζονται σε νέες καταχωρήσεις (π.χ. πρόθεμα «ΒΙΔΕΣ ΑΤΣ. ΕΞ.», με κενό μετά την τελεία).
-- Μόνο προσθετικό. Βλ. TODO.md «Διαχείριση περιγραφών».
--   tbl_description_change_items.new_description/new_category : η ΝΕΑ τιμή ανά γραμμή — ο κανόνας αντικατάστασης
--       δίνει διαφορετικό αποτέλεσμα σε κάθε περιγραφή (μένουν τα μεγέθη, αλλάζει το πρόθεμα). NULL = όπως στην
--       tbl_description_changes (migration 009: μία νέα τιμή για όλη την αλλαγή).
--   tbl_description_changes.note : κείμενο για το ιστορικό (π.χ. «Κανόνας: <regex> → <αντικατάσταση>»)
--   tbl_description_rules        : μόνιμοι κανόνες (Python re.sub) που τρέχουν σε κάθε νέα καταχώριση γραμμής
--       (_resolve_items), ΠΡΙΝ την αντιστοίχιση με υπάρχουσα περιγραφή (_canonicalize_description).

ALTER TABLE tbl_description_change_items ADD COLUMN new_description TEXT;
ALTER TABLE tbl_description_change_items ADD COLUMN new_category TEXT;
ALTER TABLE tbl_description_changes ADD COLUMN note TEXT;

CREATE TABLE tbl_description_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  pattern TEXT NOT NULL,
  replacement TEXT NOT NULL,
  created_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
