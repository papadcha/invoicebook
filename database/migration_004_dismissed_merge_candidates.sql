-- Migration 004 — Απορριφθέντα (Παράβλεψη) υποψήφια merge candidates.
-- Το κουμπί "Παράβλεψη" στα suppliers/machines/description dedup tools (tab
-- "🧹 Καθαρισμός" στο intake-tool) αφαιρούσε τη γραμμή μόνο τοπικά στο DOM — σε κάθε
-- reload/tab-reopen η αυτόματη ανίχνευση την ξανάβρισκε, αφού δεν καταγραφόταν πουθενά
-- η απόφαση. Ίδιο σκεπτικό με tbl_invoice_reviews (migration 003): ανθρώπινη απόφαση
-- πρέπει να επιβιώνει ανεξάρτητα από το τι θα ξαναέβρισκε η αυτόματη λογική.

CREATE TABLE IF NOT EXISTS tbl_dismissed_merge_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  candidate_key TEXT NOT NULL,
  dismissed_at TEXT NOT NULL,
  UNIQUE(kind, candidate_key)
);
