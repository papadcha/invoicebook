-- Migration 001 — Αρχικό σχήμα (v1)
-- Ταυτόσημο με schema.sql· υπάρχει ως ξεχωριστό αρχείο ώστε ο μηχανισμός
-- versioned migration να λειτουργεί από την πρώτη έκδοση, πριν χρειαστεί
-- ποτέ πραγματική αναβάθμιση.

CREATE TABLE IF NOT EXISTS tbl_suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  vat_number TEXT UNIQUE,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS tbl_invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER REFERENCES tbl_suppliers(id),
  doc_type TEXT,
  doc_number TEXT,
  doc_date TEXT NOT NULL,
  doc_time TEXT,
  customer_name TEXT,
  customer_vat TEXT,
  net_amount REAL,
  vat_amount REAL,
  total_amount REAL,
  payment_method TEXT,
  notes TEXT,
  source_pdf_filename TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tbl_invoice_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES tbl_invoices(id) ON DELETE CASCADE,
  code TEXT,
  description TEXT NOT NULL,
  unit TEXT,
  quantity REAL,
  unit_price REAL,
  value REAL,
  vat_pct REAL
);

CREATE TABLE IF NOT EXISTS tbl_import_staging (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_label TEXT,
  source TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invoices_doc_date ON tbl_invoices(doc_date);
CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON tbl_invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_items_invoice ON tbl_invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_staging_status ON tbl_import_staging(status);
