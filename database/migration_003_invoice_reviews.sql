-- Migration 003 — Επιθεώρηση flagged τιμολογίων (Status/Έλεγχος στο intake-tool).
-- Χειροκίνητη, ανά τιμολόγιο επιβεβαίωση ("το είδα, το αφήνω όπως είναι") — ξεχωριστό
-- από τους αυτόματους κανόνες του get_flagged_invoices(), που μπορούν να αλλάξουν
-- ελεύθερα χωρίς να χάνεται η ανθρώπινη απόφαση. Ένα επιθεωρημένο τιμολόγιο εμφανίζεται
-- πάντα ως severity='reviewed' ανεξάρτητα τι θα έλεγε η αυτόματη ταξινόμηση.

CREATE TABLE IF NOT EXISTS tbl_invoice_reviews (
  invoice_id INTEGER PRIMARY KEY REFERENCES tbl_invoices(id) ON DELETE CASCADE,
  note TEXT,
  reviewed_at TEXT NOT NULL
);
