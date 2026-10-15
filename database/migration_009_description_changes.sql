-- Migration 009 — Καταγραφή αλλαγών περιγραφής/κατηγορίας γραμμών τιμολογίων (καθαρισμός περιγραφών)
-- με δυνατότητα αναίρεσης. Μόνο προσθετικό (δύο νέοι πίνακες) — δεν αγγίζει υπάρχοντα δεδομένα.
-- Η παλιά ενοποίηση (merge_item_descriptions, λίστα υποψηφίων) ΔΕΝ γράφει εδώ· μόνο η νέα
-- αναζήτηση+επιλογή (apply_description_change). Βλ. TODO.md «Διαχείριση περιγραφών».
--   tbl_description_changes      : μία γραμμή ανά ενέργεια (τι εφαρμόστηκε, πόσες γραμμές, αν αναιρέθηκε)
--   tbl_description_change_items  : ανά γραμμή τιμολογίου η ΠΑΛΙΑ περιγραφή/κατηγορία (για την αναίρεση)
-- Αν μια γραμμή σβηστεί αργότερα (π.χ. επεξεργασία τιμολογίου με πλήρη αντικατάσταση γραμμών, που
-- ξαναδίνει νέα ids), σβήνεται και η εγγραφή της (ON DELETE CASCADE) — η αναίρεση την αναφέρει ως «χάθηκε».

CREATE TABLE tbl_description_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  new_description TEXT,   -- NULL = η περιγραφή έμεινε ίδια
  new_category TEXT,      -- NULL = η κατηγορία έμεινε ίδια
  line_count INTEGER NOT NULL,
  undone_at TEXT
);

CREATE TABLE tbl_description_change_items (
  change_id INTEGER NOT NULL REFERENCES tbl_description_changes(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES tbl_invoice_items(id) ON DELETE CASCADE,
  old_description TEXT,
  old_category TEXT,
  PRIMARY KEY (change_id, item_id)
);

CREATE INDEX idx_description_change_items_item ON tbl_description_change_items(item_id);
