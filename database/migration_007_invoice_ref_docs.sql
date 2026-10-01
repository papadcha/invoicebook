-- Migration 007 — Σχετικά παραστατικά τιμολογίου (Δελτίο Αποστολής που αναφέρει).
-- Γενικά πεδία, όχι ειδικά για εκρηκτικά: το τιμολόγιο NITROCHEM γράφει το «Σχετ. Παραστ.»
-- (π.χ. ΔΙΧΝ 19586, 6/3/2026) και, στα πιστωτικά, το δικό μας Δ.Α. επιστροφής (ΔΕ 9). Το
-- νόμιμο βιβλίο του expvault δουλεύει με αυτά (αριθμός/ημερομηνία ΔΑ), όχι με τον αριθμό και
-- την ημερομηνία του τιμολογίου.
--   ref_doc_number / ref_doc_date : «Σχετ. Παραστατικό» όπως τυπώνεται (ημερομηνία ISO)
--   own_doc_number                : μόνο πιστωτικά — το δικό μας Δ.Α. επιστροφής (π.χ. ΔΕ 9)

ALTER TABLE tbl_invoices ADD COLUMN ref_doc_number TEXT;
ALTER TABLE tbl_invoices ADD COLUMN ref_doc_date TEXT;
ALTER TABLE tbl_invoices ADD COLUMN own_doc_number TEXT;
