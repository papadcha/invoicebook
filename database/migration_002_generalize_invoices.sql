-- Migration 002 — Γενίκευση για πολλαπλές κατηγορίες (καύσιμα/επισκευές/λιπαντικά/
-- ενέργεια/...), πλέον εξωτερικές στο invoicebook. category/machine/ΕΦΚ ζουν σε επίπεδο
-- γραμμής (tbl_invoice_items), όχι τιμολογίου — ένα τιμολόγιο μπορεί να έχει γραμμές
-- διαφορετικών κατηγοριών/μηχανημάτων μαζί. tbl_machines ίδιο μοτίβο με το ήδη υπάρχον
-- tbl_suppliers (απλή λίστα, "Μπιτόνι"/"Απόθεμα" είναι απλά μία ακόμα εγγραφή, όχι
-- ειδική περίπτωση). tbl_bulk_pools/tbl_allocations υλοποιούν το 2-σταδίων μοντέλο
-- διαμοιρασμού μαζικών αγορών (πετρέλαιο/λιπαντικά σε δεξαμενή) σε συγκεκριμένα
-- μηχανήματα με την πάροδο του χρόνου.

ALTER TABLE tbl_invoices ADD COLUMN customer_doy TEXT;
ALTER TABLE tbl_invoices ADD COLUMN customer_address TEXT;
ALTER TABLE tbl_invoices ADD COLUMN customer_phone TEXT;

CREATE TABLE IF NOT EXISTS tbl_machines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  notes TEXT
);

ALTER TABLE tbl_invoice_items ADD COLUMN category TEXT;
ALTER TABLE tbl_invoice_items ADD COLUMN machine_id INTEGER REFERENCES tbl_machines(id);
ALTER TABLE tbl_invoice_items ADD COLUMN efk_eligible INTEGER NOT NULL DEFAULT 0;

-- Στάδιο 1 (μαζική καταχώρηση): μία pool ανά item που έχει σημανθεί "bulk" στο confirm.
CREATE TABLE IF NOT EXISTS tbl_bulk_pools (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_item_id INTEGER NOT NULL UNIQUE REFERENCES tbl_invoice_items(id) ON DELETE CASCADE,
  category TEXT,
  unit TEXT,
  total_quantity REAL NOT NULL,
  remaining_quantity REAL NOT NULL,
  closed INTEGER NOT NULL DEFAULT 0,
  close_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Στάδιο 2 (διαμοιρασμός): κάθε κατανομή αφαιρεί από το remaining_quantity της pool της.
CREATE TABLE IF NOT EXISTS tbl_allocations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pool_id INTEGER NOT NULL REFERENCES tbl_bulk_pools(id) ON DELETE CASCADE,
  machine_id INTEGER REFERENCES tbl_machines(id),
  quantity REAL NOT NULL,
  allocation_date TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_category ON tbl_invoice_items(category);
CREATE INDEX IF NOT EXISTS idx_items_machine ON tbl_invoice_items(machine_id);
CREATE INDEX IF NOT EXISTS idx_pools_closed ON tbl_bulk_pools(closed);
CREATE INDEX IF NOT EXISTS idx_allocations_pool ON tbl_allocations(pool_id);
