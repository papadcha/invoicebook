-- Migration 006 — Ιστορικό εξαγωγών τιμολογίων προς εξωτερικά συστήματα.
-- Γενικό (target = σε ποιο σύστημα, π.χ. 'expvault'), όχι ειδικό για ένα είδος εγγράφου:
-- μια εξαγωγή που δεν θυμάται τι έχει ήδη στείλει οδηγεί σε διπλοκαταχωρήσεις στον
-- προορισμό (π.χ. νόμιμο βιβλίο εκρηκτικών). Μία γραμμή ανά τιμολόγιο ανά εξαγωγή.

CREATE TABLE IF NOT EXISTS tbl_invoice_exports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES tbl_invoices(id) ON DELETE CASCADE,
  target TEXT NOT NULL,
  exported_at TEXT NOT NULL,
  file_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_invoice_exports_target ON tbl_invoice_exports(target, invoice_id);
