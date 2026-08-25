-- InvoiceBook — πλήρες σχήμα βάσης (τρέχουσα έκδοση)
-- Εφαρμόζεται αυτούσιο σε νέα εγκατάσταση· βλ. migration_NNN_*.sql για αναβαθμίσεις.

CREATE TABLE tbl_suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  vat_number TEXT UNIQUE,
  notes TEXT
);

CREATE TABLE tbl_invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  supplier_id INTEGER REFERENCES tbl_suppliers(id),
  doc_type TEXT,
  doc_number TEXT,
  doc_date TEXT NOT NULL,
  doc_time TEXT,
  customer_name TEXT,
  customer_vat TEXT,
  customer_doy TEXT,
  customer_address TEXT,
  customer_phone TEXT,
  net_amount REAL,
  vat_amount REAL,
  total_amount REAL,
  payment_method TEXT,
  notes TEXT,
  source_pdf_filename TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- "Μπιτόνι"/"Απόθεμα" είναι απλά μία ακόμα εγγραφή εδώ, όχι πραγματικό μηχάνημα —
-- ό,τι στόχο διαμοιρασμού βολεύει τον χειριστή.
CREATE TABLE tbl_machines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  notes TEXT
);

-- category/machine/ΕΦΚ ζουν σε επίπεδο γραμμής, όχι τιμολογίου — ένα τιμολόγιο μπορεί
-- να έχει γραμμές διαφορετικών κατηγοριών/μηχανημάτων μαζί. category είναι ελεύθερο
-- TEXT (ίδιο μοτίβο με doc_type/unit) — η ταξινόμηση ακόμα αναδύεται από πραγματικά
-- έγγραφα, δεν έχει κλειδώσει σε fixed λίστα.
CREATE TABLE tbl_invoice_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES tbl_invoices(id) ON DELETE CASCADE,
  code TEXT,
  description TEXT NOT NULL,
  unit TEXT,
  quantity REAL,
  unit_price REAL,
  value REAL,
  vat_pct REAL,
  category TEXT,
  machine_id INTEGER REFERENCES tbl_machines(id),
  efk_eligible INTEGER NOT NULL DEFAULT 0
);

-- Στάδιο 1 (μαζική καταχώρηση, π.χ. δεξαμενή πετρελαίου): μία pool ανά item που
-- σημαίνεται "bulk" στο confirm, remaining_quantity αρχικά = total_quantity.
CREATE TABLE tbl_bulk_pools (
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
CREATE TABLE tbl_allocations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pool_id INTEGER NOT NULL REFERENCES tbl_bulk_pools(id) ON DELETE CASCADE,
  machine_id INTEGER REFERENCES tbl_machines(id),
  quantity REAL NOT NULL,
  allocation_date TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL
);

-- Staged rows εν αναμονή ανθρώπινης επιβεβαίωσης πριν γίνουν πραγματικά
-- τιμολόγια/είδη. Σήμερα γεμίζει από εισαγωγή CSV/JSON· μελλοντικά ένα
-- OCR module θα μπορούσε να γράφει εδώ επίσης (source='ocr_extract').
CREATE TABLE tbl_import_staging (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_label TEXT,
  source TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);

-- Χειροκίνητη επιθεώρηση flagged τιμολογίων ("το είδα, το αφήνω όπως είναι") — βλ.
-- migration_003_invoice_reviews.sql για το σκεπτικό.
CREATE TABLE tbl_invoice_reviews (
  invoice_id INTEGER PRIMARY KEY REFERENCES tbl_invoices(id) ON DELETE CASCADE,
  note TEXT,
  reviewed_at TEXT NOT NULL
);

CREATE TABLE tbl_schema_version (
  version INTEGER NOT NULL,
  applied_at TEXT NOT NULL,
  description TEXT
);

CREATE INDEX idx_invoices_doc_date ON tbl_invoices(doc_date);
CREATE INDEX idx_invoices_supplier ON tbl_invoices(supplier_id);
CREATE INDEX idx_items_invoice ON tbl_invoice_items(invoice_id);
CREATE INDEX idx_staging_status ON tbl_import_staging(status);
CREATE INDEX idx_items_category ON tbl_invoice_items(category);
CREATE INDEX idx_items_machine ON tbl_invoice_items(machine_id);
CREATE INDEX idx_pools_closed ON tbl_bulk_pools(closed);
CREATE INDEX idx_allocations_pool ON tbl_allocations(pool_id);
