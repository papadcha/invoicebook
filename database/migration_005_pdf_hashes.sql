-- Migration 005 — Cache SHA256 ανά αρχείο του pdf_store (Layer 1 dedup).
-- Ο έλεγχος "ίδιο ακριβώς PDF σε δύο τιμολόγια" χρειάζεται hash κάθε αρχείου· ο
-- υπολογισμός για ~2700 αρχεία (~1,4 GB) κοστίζει δευτερόλεπτα, οπότε κρατιέται εδώ και
-- ξαναϋπολογίζεται μόνο όταν αλλάξει μέγεθος/mtime του αρχείου. Καθαρά cache — μπορεί να
-- αδειάσει οποτεδήποτε χωρίς απώλεια πληροφορίας.

CREATE TABLE IF NOT EXISTS tbl_pdf_hashes (
  filename TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  sha256 TEXT NOT NULL
);
