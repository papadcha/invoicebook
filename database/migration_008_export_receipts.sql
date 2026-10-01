-- Migration 008 — Αποδεικτικό εισαγωγής για τις εξαγωγές προς εξωτερικά συστήματα (expvault).
-- Το «✓ Εξήχθη» σήμαινε μόνο ότι γράφτηκε αρχείο· δεν ήξερε αν το νόμιμο βιβλίο πράγματι το δέχτηκε
-- (βλ. ΔΕ 10 που δεν είχε περαστεί). Τώρα κάθε εξαγωγή έχει export_id και θυμάται ΤΙ εξήχθη (lines_json)·
-- όταν το ExpVault+ βγάλει αρχείο-απόδειξη, το invoicebook το φορτώνει και συγκρίνει.
--   import_status: NULL = εκκρεμεί επιβεβαίωση, 'ok' = εισήχθη όπως εξήχθη, 'mismatch' = εισήχθη με διαφορές

ALTER TABLE tbl_invoice_exports ADD COLUMN export_id TEXT;
ALTER TABLE tbl_invoice_exports ADD COLUMN lines_json TEXT;
ALTER TABLE tbl_invoice_exports ADD COLUMN imported_at TEXT;
ALTER TABLE tbl_invoice_exports ADD COLUMN import_status TEXT;
ALTER TABLE tbl_invoice_exports ADD COLUMN import_note TEXT;
ALTER TABLE tbl_invoice_exports ADD COLUMN receipt_file TEXT;
CREATE INDEX IF NOT EXISTS idx_invoice_exports_export_id ON tbl_invoice_exports(export_id);
