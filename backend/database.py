# -*- coding: utf-8 -*-
"""
database.py — SQLite access layer για το InvoiceBook.

DB_NAME ορίζεται δυναμικά από το bridge.py πριν κληθεί initialize_database().
"""
import sqlite3
import os
import re
import json
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone

DB_NAME = None       # ορίζεται από bridge.py
PDF_STORE_DIR = None  # ορίζεται από bridge.py — φάκελος όπου "υιοθετούνται" τα PDF

_local_db_dir = os.path.dirname(os.path.abspath(__file__ + '/../database'))
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'schema.sql')
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database')

CURRENT_SCHEMA_VERSION = 1

migration_files = {
    1: os.path.join(MIGRATIONS_DIR, 'migration_001_initial_schema.sql'),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_schema_version(conn):
    try:
        row = conn.execute('SELECT MAX(version) as v FROM tbl_schema_version').fetchone()
        return row['v'] or 0
    except sqlite3.OperationalError:
        return 0


def _run_migration_sql(conn, sql_path, version):
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()
    conn.executescript(sql)
    conn.execute(
        'INSERT OR REPLACE INTO tbl_schema_version (version, applied_at, description) VALUES (?, ?, ?)',
        (version, _now(), f'Auto-migration {version}')
    )
    conn.commit()


def initialize_database():
    is_fresh = not os.path.exists(DB_NAME) or os.path.getsize(DB_NAME) == 0
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        if is_fresh:
            with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
                schema = f.read()
            conn.executescript(schema)
            conn.execute(
                'INSERT INTO tbl_schema_version (version, applied_at, description) VALUES (?, ?, ?)',
                (CURRENT_SCHEMA_VERSION, _now(), f'Initial schema (full v{CURRENT_SCHEMA_VERSION})')
            )
            conn.commit()
            return

        ver = _get_schema_version(conn)
        if ver >= CURRENT_SCHEMA_VERSION:
            return

        for v in range(ver + 1, CURRENT_SCHEMA_VERSION + 1):
            sql_path = migration_files.get(v)
            if not sql_path:
                raise RuntimeError(f'Λείπει αρχείο migration για την έκδοση {v}')
            _run_migration_sql(conn, sql_path, v)
    finally:
        conn.close()


# ── ΠΡΟΜΗΘΕΥΤΕΣ ──────────────────────────────────────────────────────────────

def get_all_suppliers():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM tbl_suppliers ORDER BY name').fetchall()
        return [dict(r) for r in rows]


def add_supplier(name, vat_number=None, notes=None):
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO tbl_suppliers (name, vat_number, notes) VALUES (?, ?, ?)',
            (name, vat_number or None, notes)
        )
        return cur.lastrowid


def update_supplier(supplier_id, name, vat_number=None, notes=None):
    with get_db() as conn:
        conn.execute(
            'UPDATE tbl_suppliers SET name=?, vat_number=?, notes=? WHERE id=?',
            (name, vat_number or None, notes, supplier_id)
        )


def delete_supplier(supplier_id):
    with get_db() as conn:
        used = conn.execute(
            'SELECT COUNT(*) as c FROM tbl_invoices WHERE supplier_id=?', (supplier_id,)
        ).fetchone()['c']
        if used:
            raise ValueError('Δεν μπορεί να διαγραφεί — υπάρχουν τιμολόγια αυτού του προμηθευτή')
        conn.execute('DELETE FROM tbl_suppliers WHERE id=?', (supplier_id,))


# ── ΤΙΜΟΛΟΓΙΑ ─────────────────────────────────────────────────────────────────

def _pdf_available(filename):
    if not filename or not PDF_STORE_DIR:
        return False
    return os.path.exists(os.path.join(PDF_STORE_DIR, filename))


def _row_to_invoice(conn, row):
    inv = dict(row)
    inv['pdf_available'] = _pdf_available(inv.get('source_pdf_filename'))
    items = conn.execute(
        'SELECT * FROM tbl_invoice_items WHERE invoice_id=? ORDER BY id', (inv['id'],)
    ).fetchall()
    inv['items'] = [dict(i) for i in items]
    return inv


def get_invoices(date_from=None, date_to=None, supplier_id=None):
    with get_db() as conn:
        q = '''SELECT i.*, s.name as supplier_name FROM tbl_invoices i
               LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id WHERE 1=1'''
        params = []
        if date_from:
            q += ' AND i.doc_date >= ?'
            params.append(date_from)
        if date_to:
            q += ' AND i.doc_date <= ?'
            params.append(date_to)
        if supplier_id:
            q += ' AND i.supplier_id = ?'
            params.append(supplier_id)
        q += ' ORDER BY i.doc_date DESC, i.id DESC'
        rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['pdf_available'] = _pdf_available(d.get('source_pdf_filename'))
            out.append(d)
        return out


def get_invoice(invoice_id):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM tbl_invoices WHERE id=?', (invoice_id,)).fetchone()
        if not row:
            raise ValueError('Το τιμολόγιο δεν βρέθηκε')
        return _row_to_invoice(conn, row)


def _insert_invoice(conn, header, items):
    now = _now()
    cur = conn.execute(
        '''INSERT INTO tbl_invoices
           (supplier_id, doc_type, doc_number, doc_date, doc_time, customer_name, customer_vat,
            net_amount, vat_amount, total_amount, payment_method, notes, source_pdf_filename,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (header.get('supplier_id'), header.get('doc_type'), header.get('doc_number'),
         header['doc_date'], header.get('doc_time'), header.get('customer_name'),
         header.get('customer_vat'), header.get('net_amount'), header.get('vat_amount'),
         header.get('total_amount'), header.get('payment_method'), header.get('notes'),
         header.get('source_pdf_filename'), now, now)
    )
    invoice_id = cur.lastrowid
    for it in (items or []):
        conn.execute(
            '''INSERT INTO tbl_invoice_items
               (invoice_id, code, description, unit, quantity, unit_price, value, vat_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (invoice_id, it.get('code'), it.get('description') or '', it.get('unit'),
             it.get('quantity'), it.get('unit_price'), it.get('value'), it.get('vat_pct'))
        )
    return invoice_id


def add_invoice(header, items=None):
    with get_db() as conn:
        return _insert_invoice(conn, header, items)


def update_invoice(invoice_id, header, items=None):
    with get_db() as conn:
        conn.execute(
            '''UPDATE tbl_invoices SET
               supplier_id=?, doc_type=?, doc_number=?, doc_date=?, doc_time=?,
               customer_name=?, customer_vat=?, net_amount=?, vat_amount=?, total_amount=?,
               payment_method=?, notes=?, source_pdf_filename=?, updated_at=?
               WHERE id=?''',
            (header.get('supplier_id'), header.get('doc_type'), header.get('doc_number'),
             header['doc_date'], header.get('doc_time'), header.get('customer_name'),
             header.get('customer_vat'), header.get('net_amount'), header.get('vat_amount'),
             header.get('total_amount'), header.get('payment_method'), header.get('notes'),
             header.get('source_pdf_filename'), _now(), invoice_id)
        )
        conn.execute('DELETE FROM tbl_invoice_items WHERE invoice_id=?', (invoice_id,))
        for it in (items or []):
            conn.execute(
                '''INSERT INTO tbl_invoice_items
                   (invoice_id, code, description, unit, quantity, unit_price, value, vat_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (invoice_id, it.get('code'), it.get('description') or '', it.get('unit'),
                 it.get('quantity'), it.get('unit_price'), it.get('value'), it.get('vat_pct'))
            )


def delete_invoice(invoice_id):
    with get_db() as conn:
        conn.execute('DELETE FROM tbl_invoices WHERE id=?', (invoice_id,))


# ── PDF ΣΑΡΩΜΕΝΩΝ ΤΙΜΟΛΟΓΙΩΝ ──────────────────────────────────────────────────
# "Υιοθέτηση" — το αρχείο ΜΕΤΑΚΙΝΕΙΤΑΙ (όχι αντιγραφή) μέσα στο pdf_store της
# εφαρμογής, ώστε να μην εξαρτόμαστε από το αν θα μείνει εκεί που ήταν αρχικά.

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def _sanitize_filename(name):
    return _INVALID_FILENAME_CHARS.sub('_', name)


def attach_pdf(invoice_id, source_path):
    if not PDF_STORE_DIR:
        raise RuntimeError('PDF_STORE_DIR δεν έχει οριστεί')
    if not os.path.exists(source_path):
        raise ValueError(f'Το αρχείο δεν βρέθηκε: {source_path}')

    with get_db() as conn:
        row = conn.execute('SELECT id FROM tbl_invoices WHERE id=?', (invoice_id,)).fetchone()
        if not row:
            raise ValueError('Το τιμολόγιο δεν βρέθηκε')

        os.makedirs(PDF_STORE_DIR, exist_ok=True)
        original_name = _sanitize_filename(os.path.basename(source_path))
        stored_name = f'{invoice_id}_{original_name}'
        dest_path = os.path.join(PDF_STORE_DIR, stored_name)

        if os.path.abspath(source_path) != os.path.abspath(dest_path):
            shutil.move(source_path, dest_path)

        conn.execute(
            'UPDATE tbl_invoices SET source_pdf_filename=?, updated_at=? WHERE id=?',
            (stored_name, _now(), invoice_id)
        )
        return stored_name


# ── ΕΙΣΑΓΩΓΗ (STAGING) ────────────────────────────────────────────────────────

def _find_or_create_supplier(conn, name, vat_number=None):
    if not name:
        return None
    row = None
    if vat_number:
        row = conn.execute('SELECT id FROM tbl_suppliers WHERE vat_number=?', (vat_number,)).fetchone()
    if not row:
        row = conn.execute('SELECT id FROM tbl_suppliers WHERE name=?', (name,)).fetchone()
    if row:
        return row['id']
    cur = conn.execute(
        'INSERT INTO tbl_suppliers (name, vat_number) VALUES (?, ?)', (name, vat_number or None)
    )
    return cur.lastrowid


def import_staging_rows(rows, batch_label=None, source='csv_import'):
    """rows: λίστα από dict, ένα ανά τιμολόγιο, με προαιρετικό nested 'items'."""
    with get_db() as conn:
        created = []
        for row in rows:
            raw = json.dumps(row, ensure_ascii=False)
            cur = conn.execute(
                '''INSERT INTO tbl_import_staging (batch_label, source, raw_json, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)''',
                (batch_label, source, raw, _now())
            )
            created.append(cur.lastrowid)
        return created


def get_staging_batch(batch_label=None, status=None):
    with get_db() as conn:
        q = 'SELECT * FROM tbl_import_staging WHERE 1=1'
        params = []
        if batch_label:
            q += ' AND batch_label=?'
            params.append(batch_label)
        if status:
            q += ' AND status=?'
            params.append(status)
        q += ' ORDER BY id'
        rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['data'] = json.loads(d['raw_json'])
            out.append(d)
        return out


def confirm_staging_row(staging_id):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM tbl_import_staging WHERE id=?', (staging_id,)).fetchone()
        if not row:
            raise ValueError('Η εγγραφή εισαγωγής δεν βρέθηκε')
        if row['status'] != 'pending':
            raise ValueError('Η εγγραφή έχει ήδη επεξεργαστεί')
        data = json.loads(row['raw_json'])
        items = data.pop('items', [])
        supplier_id = _find_or_create_supplier(conn, data.get('supplier_name'), data.get('supplier_vat'))
        header = {
            'supplier_id': supplier_id,
            'doc_type': data.get('doc_type'),
            'doc_number': data.get('doc_number'),
            'doc_date': data.get('doc_date'),
            'doc_time': data.get('doc_time'),
            'customer_name': data.get('customer_name'),
            'customer_vat': data.get('customer_vat'),
            'net_amount': data.get('net_amount'),
            'vat_amount': data.get('vat_amount'),
            'total_amount': data.get('total_amount'),
            'payment_method': data.get('payment_method'),
            'notes': data.get('notes'),
            'source_pdf_filename': data.get('source_pdf_filename'),
        }
        invoice_id = _insert_invoice(conn, header, items)
        conn.execute("UPDATE tbl_import_staging SET status='confirmed' WHERE id=?", (staging_id,))
        return invoice_id


def reject_staging_row(staging_id):
    with get_db() as conn:
        conn.execute("UPDATE tbl_import_staging SET status='rejected' WHERE id=?", (staging_id,))


# ── ΑΝΑΦΟΡΕΣ ──────────────────────────────────────────────────────────────────

def get_summary(year=None, month=None):
    with get_db() as conn:
        q = '''SELECT strftime('%Y', doc_date) as yr, strftime('%m', doc_date) as mo,
                      COUNT(*) as invoice_count,
                      SUM(net_amount) as net_total, SUM(vat_amount) as vat_total,
                      SUM(total_amount) as grand_total
               FROM tbl_invoices WHERE 1=1'''
        params = []
        if year:
            q += " AND strftime('%Y', doc_date) = ?"
            params.append(str(year))
        if month:
            q += " AND strftime('%m', doc_date) = ?"
            params.append(f'{int(month):02d}')
        q += ' GROUP BY yr, mo ORDER BY yr DESC, mo DESC'
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
