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

CURRENT_SCHEMA_VERSION = 2

migration_files = {
    1: os.path.join(MIGRATIONS_DIR, 'migration_001_initial_schema.sql'),
    2: os.path.join(MIGRATIONS_DIR, 'migration_002_generalize_invoices.sql'),
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


def _find_duplicate(conn, header, exclude_id=None):
    """Ελέγχει αν υπάρχει ήδη τιμολόγιο με ίδιο (doc_number, doc_date, supplier_id).
    Ο προμηθευτής συγκρίνεται ήδη-resolved ως id (μέσω _find_or_create_supplier),
    οπότε δεν χρειάζεται ξεχωριστή κανονικοποίηση ονόματος εδώ (σε αντίθεση με του
    πρώην fuel domain's _find_duplicate, που συνέκρινε raw supplier_name string)."""
    doc_number = header.get('doc_number')
    doc_date = header.get('doc_date')
    supplier_id = header.get('supplier_id')
    if not doc_number or not doc_date or not supplier_id:
        return None
    row = conn.execute(
        'SELECT * FROM tbl_invoices WHERE doc_number=? AND doc_date=? AND supplier_id=?',
        (doc_number, doc_date, supplier_id)
    ).fetchone()
    if row and (exclude_id is None or row['id'] != exclude_id):
        return row
    return None


def _insert_invoice(conn, header, items):
    duplicate = _find_duplicate(conn, header)
    if duplicate is not None:
        raise ValueError(
            f'Πιθανό διπλότυπο — υπάρχει ήδη τιμολόγιο id={duplicate["id"]} '
            f'({duplicate["doc_date"]}, σύνολο {duplicate["total_amount"]}) με ίδιο '
            f'αριθμό παραστατικού, ημερομηνία και προμηθευτή.'
        )
    now = _now()
    cur = conn.execute(
        '''INSERT INTO tbl_invoices
           (supplier_id, doc_type, doc_number, doc_date, doc_time, customer_name, customer_vat,
            customer_doy, customer_address, customer_phone,
            net_amount, vat_amount, total_amount, payment_method, notes, source_pdf_filename,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (header.get('supplier_id'), header.get('doc_type'), header.get('doc_number'),
         header['doc_date'], header.get('doc_time'), header.get('customer_name'),
         header.get('customer_vat'), header.get('customer_doy'), header.get('customer_address'),
         header.get('customer_phone'), header.get('net_amount'), header.get('vat_amount'),
         header.get('total_amount'), header.get('payment_method'), header.get('notes'),
         header.get('source_pdf_filename'), now, now)
    )
    invoice_id = cur.lastrowid
    for it in (items or []):
        conn.execute(
            '''INSERT INTO tbl_invoice_items
               (invoice_id, code, description, unit, quantity, unit_price, value, vat_pct,
                category, machine_id, efk_eligible)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (invoice_id, it.get('code'), it.get('description') or '', it.get('unit'),
             it.get('quantity'), it.get('unit_price'), it.get('value'), it.get('vat_pct'),
             it.get('category'), it.get('machine_id'), bool(it.get('efk_eligible')))
        )
    return invoice_id


def add_invoice(header, items=None):
    with get_db() as conn:
        return _insert_invoice(conn, header, items)


def update_invoice(invoice_id, header, items=None):
    """items με 'id' (υπάρχουσα γραμμή) γίνονται UPDATE in-place — κρατάει
    σταθερό το id ώστε τυχόν tbl_bulk_pools.invoice_item_id FK να μην κοπεί
    (ON DELETE CASCADE θα διέγραφε αθόρυβα το ιστορικό διαμοιρασμού). items
    χωρίς 'id' εισάγονται ως νέα. Γραμμές που υπήρχαν αλλά δεν εμφανίζονται
    καθόλου στη νέα λίστα διαγράφονται — ίδια συμπεριφορά "πλήρης
    αντικατάσταση" με πριν για callers που δεν στέλνουν ποτέ 'id' (π.χ. το
    ήδη υπάρχον native UI του invoicebook)."""
    with get_db() as conn:
        duplicate = _find_duplicate(conn, header, exclude_id=invoice_id)
        if duplicate is not None:
            raise ValueError(
                f'Πιθανό διπλότυπο — υπάρχει ήδη τιμολόγιο id={duplicate["id"]} '
                f'({duplicate["doc_date"]}, σύνολο {duplicate["total_amount"]}) με ίδιο '
                f'αριθμό παραστατικού, ημερομηνία και προμηθευτή.'
            )
        conn.execute(
            '''UPDATE tbl_invoices SET
               supplier_id=?, doc_type=?, doc_number=?, doc_date=?, doc_time=?,
               customer_name=?, customer_vat=?, customer_doy=?, customer_address=?, customer_phone=?,
               net_amount=?, vat_amount=?, total_amount=?,
               payment_method=?, notes=?, source_pdf_filename=?, updated_at=?
               WHERE id=?''',
            (header.get('supplier_id'), header.get('doc_type'), header.get('doc_number'),
             header['doc_date'], header.get('doc_time'), header.get('customer_name'),
             header.get('customer_vat'), header.get('customer_doy'), header.get('customer_address'),
             header.get('customer_phone'), header.get('net_amount'), header.get('vat_amount'),
             header.get('total_amount'), header.get('payment_method'), header.get('notes'),
             header.get('source_pdf_filename'), _now(), invoice_id)
        )

        keep_ids = set()
        for it in (items or []):
            item_id = it.get('id')
            if item_id:
                conn.execute(
                    '''UPDATE tbl_invoice_items SET code=?, description=?, unit=?, quantity=?,
                       unit_price=?, value=?, vat_pct=?, category=?, machine_id=?, efk_eligible=?
                       WHERE id=? AND invoice_id=?''',
                    (it.get('code'), it.get('description') or '', it.get('unit'), it.get('quantity'),
                     it.get('unit_price'), it.get('value'), it.get('vat_pct'), it.get('category'),
                     it.get('machine_id'), bool(it.get('efk_eligible')), item_id, invoice_id)
                )
                keep_ids.add(item_id)
            else:
                cur = conn.execute(
                    '''INSERT INTO tbl_invoice_items
                       (invoice_id, code, description, unit, quantity, unit_price, value, vat_pct,
                        category, machine_id, efk_eligible)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (invoice_id, it.get('code'), it.get('description') or '', it.get('unit'),
                     it.get('quantity'), it.get('unit_price'), it.get('value'), it.get('vat_pct'),
                     it.get('category'), it.get('machine_id'), bool(it.get('efk_eligible')))
                )
                keep_ids.add(cur.lastrowid)

        existing_ids = {r['id'] for r in conn.execute(
            'SELECT id FROM tbl_invoice_items WHERE invoice_id=?', (invoice_id,)
        ).fetchall()}
        for stale_id in existing_ids - keep_ids:
            conn.execute('DELETE FROM tbl_invoice_items WHERE id=?', (stale_id,))


def delete_invoice(invoice_id):
    """Διαγράφει ολόκληρο το τιμολόγιο (header + όλες τις γραμμές του, μέσω
    ON DELETE CASCADE). Μπλοκάρει αν κάποια bulk γραμμή του έχει ήδη
    διαμοιρασμό σε μηχανήματα (tbl_allocations) — το cascade θα το έσβηνε
    αθόρυβα μαζί (ίδιος κίνδυνος με το παλιό update_invoice bug, βλ. πάνω),
    κι αυτό είναι πραγματικό ιστορικό κατανάλωσης, όχι απλά staging data."""
    with get_db() as conn:
        alloc_count = conn.execute(
            '''SELECT COUNT(*) FROM tbl_allocations a
               JOIN tbl_bulk_pools p ON p.id = a.pool_id
               JOIN tbl_invoice_items it ON it.id = p.invoice_item_id
               WHERE it.invoice_id = ?''', (invoice_id,)
        ).fetchone()[0]
        if alloc_count:
            raise ValueError(
                f'Δεν διαγράφεται — υπάρχουν {alloc_count} καταχωρημένοι διαμοιρασμοί σε '
                f'μηχανήματα πάνω σε bulk γραμμή αυτού του τιμολογίου. Αναίρεσε πρώτα τους '
                f'διαμοιρασμούς (tab Αποθέματα προς Διαμοιρασμό) αν πραγματικά χρειάζεται διαγραφή.'
            )
        conn.execute('DELETE FROM tbl_invoices WHERE id=?', (invoice_id,))


# ── PDF ΣΑΡΩΜΕΝΩΝ ΤΙΜΟΛΟΓΙΩΝ ──────────────────────────────────────────────────
# "Υιοθέτηση" — το αρχείο ΜΕΤΑΚΙΝΕΙΤΑΙ (όχι αντιγραφή) μέσα στο pdf_store της
# εφαρμογής, ώστε να μην εξαρτόμαστε από το αν θα μείνει εκεί που ήταν αρχικά.

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def _sanitize_filename(name):
    return _INVALID_FILENAME_CHARS.sub('_', name)


def _build_pdf_filename(conn, invoice_id):
    """Ανθρωπο-αναγνώσιμο όνομα 'yyyy.mm.dd Προμηθευτής (Αρ.Παραστ).pdf' — πρώην
    fuel domain's μοτίβο (βλ. intake-tool), υιοθετημένο εδώ αντί του παλιού
    '{id}_{original_name}' ώστε τα PDF να είναι browsable από τον χειριστή (π.χ. για
    τον φάκελο ΕΦΚ), όχι μόνο εσωτερικά αναγνωρίσιμα."""
    row = conn.execute(
        '''SELECT i.doc_date, i.doc_number, s.name as supplier_name
           FROM tbl_invoices i LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
           WHERE i.id=?''', (invoice_id,)
    ).fetchone()
    if not row:
        raise ValueError('Το τιμολόγιο δεν βρέθηκε')
    date = (row['doc_date'] or '').replace('/', '-')
    parts = date.split('-')
    date_part = '.'.join(parts) if len(parts) == 3 else (date or 'agnosti-imerominia')
    supplier = _sanitize_filename((row['supplier_name'] or 'Άγνωστος Προμηθευτής').strip())
    doc_number = row['doc_number']
    base = f'{date_part} {supplier}'
    if doc_number:
        base += f' ({_sanitize_filename(str(doc_number))})'
    return base + '.pdf'


def attach_pdf(invoice_id, source_path):
    if not PDF_STORE_DIR:
        raise RuntimeError('PDF_STORE_DIR δεν έχει οριστεί')
    if not os.path.exists(source_path):
        raise ValueError(f'Το αρχείο δεν βρέθηκε: {source_path}')

    with get_db() as conn:
        filename = _build_pdf_filename(conn, invoice_id)
        os.makedirs(PDF_STORE_DIR, exist_ok=True)
        stem, ext = os.path.splitext(filename)
        dest_path = os.path.join(PDF_STORE_DIR, filename)
        counter = 2
        while os.path.exists(dest_path):
            dest_path = os.path.join(PDF_STORE_DIR, f'{stem} ({counter}){ext}')
            counter += 1
        stored_name = os.path.basename(dest_path)

        if os.path.abspath(source_path) != os.path.abspath(dest_path):
            shutil.move(source_path, dest_path)

        conn.execute(
            'UPDATE tbl_invoices SET source_pdf_filename=?, updated_at=? WHERE id=?',
            (stored_name, _now(), invoice_id)
        )
        return stored_name


def get_invoice_items_by_category(category=None, date_from=None, date_to=None):
    """Μία γραμμή ανά αποτέλεσμα (item), με τα header πεδία του τιμολογίου του
    "flattened" πάνω — ισοδύναμο του πρώην fuel domain's list_invoices(), αλλά σε
    επίπεδο γραμμής (ένα τιμολόγιο μπορεί να συνεισφέρει 0, 1 ή πολλές γραμμές
    στην ίδια κατηγορία). Χρησιμοποιείται από τα tabs Καύσιμα/Επισκευές/... του
    intake-tool για αναζήτηση/περιήγηση/διόρθωση ανά κατηγορία. category=None
    (ή κενό) = καμία στήλωση κατηγορίας — "Όλες" στο UI."""
    with get_db() as conn:
        q = '''SELECT it.id as item_id, it.code, it.description, it.unit, it.quantity,
                      it.unit_price, it.value, it.vat_pct, it.category, it.machine_id,
                      it.efk_eligible, m.name as machine_name,
                      i.id as invoice_id, i.doc_type, i.doc_number, i.doc_date, i.doc_time,
                      i.customer_name, i.customer_vat, i.customer_doy, i.customer_address,
                      i.customer_phone, i.net_amount, i.vat_amount, i.total_amount,
                      i.payment_method, i.notes, i.source_pdf_filename,
                      s.name as supplier_name, s.vat_number as supplier_vat
               FROM tbl_invoice_items it
               JOIN tbl_invoices i ON i.id = it.invoice_id
               LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
               LEFT JOIN tbl_machines m ON m.id = it.machine_id
               WHERE 1=1'''
        params = []
        if category:
            q += ' AND it.category = ?'
            params.append(category)
        if date_from:
            q += ' AND i.doc_date >= ?'
            params.append(date_from)
        if date_to:
            q += ' AND i.doc_date <= ?'
            params.append(date_to)
        q += ' ORDER BY i.doc_date DESC, i.id DESC'
        rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['pdf_available'] = _pdf_available(d.get('source_pdf_filename'))
            out.append(d)
        return out


def list_categories():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM tbl_invoice_items WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ).fetchall()
        return [r['category'] for r in rows]


# ── ΜΗΧΑΝΗΜΑΤΑ / ΣΤΟΧΟΙ ΔΙΑΜΟΙΡΑΣΜΟΥ ──────────────────────────────────────────
# Απλή λίστα, ίδιο μοτίβο με tbl_suppliers — "Μπιτόνι"/"Απόθεμα" είναι απλά μία
# ακόμα εγγραφή εδώ, όχι πραγματικό μηχάνημα· ο χειριστής προσθέτει ό,τι βολεύει.

def list_machines():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM tbl_machines ORDER BY name').fetchall()
        return [dict(r) for r in rows]


def _find_or_create_machine(conn, name):
    if not name:
        return None
    row = conn.execute('SELECT id FROM tbl_machines WHERE name=?', (name,)).fetchone()
    if row:
        return row['id']
    cur = conn.execute('INSERT INTO tbl_machines (name) VALUES (?)', (name,))
    return cur.lastrowid


# ── ΕΙΣΑΓΩΓΗ (STAGING) ────────────────────────────────────────────────────────

def _resolve_header(conn, data):
    supplier_id = _find_or_create_supplier(conn, data.get('supplier_name'), data.get('supplier_vat'))
    return {
        'supplier_id': supplier_id,
        'doc_type': data.get('doc_type'),
        'doc_number': data.get('doc_number'),
        'doc_date': data.get('doc_date'),
        'doc_time': data.get('doc_time'),
        'customer_name': data.get('customer_name'),
        'customer_vat': data.get('customer_vat'),
        'customer_doy': data.get('customer_doy'),
        'customer_address': data.get('customer_address'),
        'customer_phone': data.get('customer_phone'),
        'net_amount': data.get('net_amount'),
        'vat_amount': data.get('vat_amount'),
        'total_amount': data.get('total_amount'),
        'payment_method': data.get('payment_method'),
        'notes': data.get('notes'),
        'source_pdf_filename': data.get('source_pdf_filename'),
    }


def _resolve_items(conn, items):
    """machine_id λύνεται από machine_name ΜΟΝΟ όταν το κλειδί υπάρχει (ρητά
    δοσμένο από τον χειριστή/staging JSON) — αλλιώς μένει ό,τι ήδη έχει το item
    dict (π.χ. ήδη-resolved machine_id από γραμμή που διαβάστηκε από τη βάση,
    βλ. update_invoice_from_data). Χωρίς αυτή τη διάκριση, μια αναγγική γραμμή
    θα έχανε το machine_id της κάθε φορά που ενημερώνεται μια ΑΛΛΗ γραμμή του
    ίδιου τιμολογίου."""
    resolved = []
    for it in items:
        r = dict(it)
        if 'machine_name' in r:
            r['machine_id'] = _find_or_create_machine(conn, r.get('machine_name'))
        resolved.append(r)
    return resolved


def _normalize_vat(v):
    """Αγνοεί το πρόθεμα χώρας ("EL") και κενά/παύλες — "EL094119164" και
    "094119164" πρέπει να ταιριάζουν στον ίδιο προμηθευτή (βλ. διπλότυπο
    ΠΑΠΑΝΤΩΝΙΟΥ Α.Β.Ε.Ε., 2026-08-23)."""
    if not v:
        return None
    v = str(v).strip().upper().replace(' ', '').replace('-', '')
    if v.startswith('EL'):
        v = v[2:]
    return v or None


def _find_or_create_supplier(conn, name, vat_number=None):
    if not name:
        return None
    row = None
    norm_vat = _normalize_vat(vat_number)
    if norm_vat:
        for r in conn.execute('SELECT id, vat_number FROM tbl_suppliers WHERE vat_number IS NOT NULL'):
            if _normalize_vat(r['vat_number']) == norm_vat:
                row = r
                break
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
        items = data.pop('items', []) or []
        header = _resolve_header(conn, data)
        resolved_items = _resolve_items(conn, items)
        invoice_id = _insert_invoice(conn, header, resolved_items)

        inserted_item_rows = conn.execute(
            'SELECT id FROM tbl_invoice_items WHERE invoice_id=? ORDER BY id', (invoice_id,)
        ).fetchall()
        for item_row, orig_item in zip(inserted_item_rows, items):
            if orig_item.get('bulk'):
                _create_bulk_pool(conn, item_row['id'], orig_item)

        conn.execute("UPDATE tbl_import_staging SET status='confirmed' WHERE id=?", (staging_id,))
        return invoice_id


def reject_staging_row(staging_id):
    with get_db() as conn:
        conn.execute("UPDATE tbl_import_staging SET status='rejected' WHERE id=?", (staging_id,))


def update_invoice_from_data(invoice_id, data):
    """Ίδιο raw σχήμα με ένα staging row (ονόματα προμηθευτή/μηχανήματος, όχι
    ids) — το UI της διόρθωσης δεν χρειάζεται δική του λογική resolution.
    data['items'] περιέχει ΜΟΝΟ τη γραμμή που επεξεργάζεται ο χειριστής (με
    'id' αν είναι ήδη υπάρχουσα) — τυχόν άλλες γραμμές του ίδιου τιμολογίου
    διαβάζονται από τη βάση και μένουν αμετάβλητες (ίδιο id, βλ.
    update_invoice — δεν κόβεται το FK τυχόν bulk pool τους)."""
    with get_db() as conn:
        existing_items = [dict(r) for r in conn.execute(
            'SELECT * FROM tbl_invoice_items WHERE invoice_id=? ORDER BY id', (invoice_id,)
        ).fetchall()]
        edited_by_id = {it.get('id'): it for it in (data.get('items') or []) if it.get('id')}
        merged_items = [edited_by_id.pop(ex['id'], ex) for ex in existing_items]
        for it in edited_by_id.values():
            it = dict(it)
            it.pop('id', None)  # δεν ταίριαξε σε υπάρχουσα γραμμή -> νέα εγγραφή
            merged_items.append(it)

        header = _resolve_header(conn, data)
        resolved_items = _resolve_items(conn, merged_items)

    update_invoice(invoice_id, header, resolved_items)
    return invoice_id


# ── ΜΑΖΙΚΕΣ ΚΑΤΑΧΩΡΗΣΕΙΣ / ΔΙΑΜΟΙΡΑΣΜΟΣ (2 στάδια) ────────────────────────────
# Στάδιο 1: μια bulk καταχώρηση (π.χ. δεξαμενή πετρελαίου) δημιουργεί ένα
# "απόθεμα προς διαμοιρασμό" με remaining_quantity = όλη η αρχική ποσότητα.
# Στάδιο 2: κατανομές προς μηχανήματα/στόχους αφαιρούν από το remaining μέχρι να
# μηδενίσει — ή να κλείσει με υπόλοιπο + υποχρεωτική σημείωση.

def _create_bulk_pool(conn, invoice_item_id, item_data):
    total = item_data.get('quantity')
    if total is None:
        raise ValueError('Δεν μπορεί να δημιουργηθεί απόθεμα προς διαμοιρασμό χωρίς ποσότητα')
    now = _now()
    conn.execute(
        '''INSERT INTO tbl_bulk_pools
           (invoice_item_id, category, unit, total_quantity, remaining_quantity, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (invoice_item_id, item_data.get('category'), item_data.get('unit'), total, total, now, now)
    )


def list_open_bulk_pools():
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT p.*, it.description, i.doc_date, i.doc_number, s.name as supplier_name
               FROM tbl_bulk_pools p
               JOIN tbl_invoice_items it ON it.id = p.invoice_item_id
               JOIN tbl_invoices i ON i.id = it.invoice_id
               LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
               WHERE p.closed = 0
               ORDER BY i.doc_date'''
        ).fetchall()
        return [dict(r) for r in rows]


def add_allocation(pool_id, machine_name, quantity, allocation_date, notes=None):
    if quantity is None or quantity <= 0:
        raise ValueError('Η ποσότητα κατανομής πρέπει να είναι θετικός αριθμός')
    with get_db() as conn:
        pool = conn.execute('SELECT * FROM tbl_bulk_pools WHERE id=?', (pool_id,)).fetchone()
        if not pool:
            raise ValueError('Το απόθεμα δεν βρέθηκε')
        if pool['closed']:
            raise ValueError('Το απόθεμα είναι ήδη κλειστό')
        if quantity > pool['remaining_quantity']:
            raise ValueError(
                f'Η ποσότητα ({quantity}) ξεπερνά το διαθέσιμο υπόλοιπο ({pool["remaining_quantity"]})'
            )
        machine_id = _find_or_create_machine(conn, machine_name)
        now = _now()
        conn.execute(
            '''INSERT INTO tbl_allocations (pool_id, machine_id, quantity, allocation_date, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (pool_id, machine_id, quantity, allocation_date, notes, now)
        )
        remaining = pool['remaining_quantity'] - quantity
        conn.execute(
            'UPDATE tbl_bulk_pools SET remaining_quantity=?, updated_at=? WHERE id=?',
            (remaining, now, pool_id)
        )
        return {'remaining_quantity': remaining}


def close_bulk_pool(pool_id, note=None):
    with get_db() as conn:
        pool = conn.execute('SELECT * FROM tbl_bulk_pools WHERE id=?', (pool_id,)).fetchone()
        if not pool:
            raise ValueError('Το απόθεμα δεν βρέθηκε')
        if pool['remaining_quantity'] > 0 and not note:
            raise ValueError('Απαιτείται σημείωση για κλείσιμο με μη μηδενικό υπόλοιπο')
        conn.execute(
            'UPDATE tbl_bulk_pools SET closed=1, close_note=?, updated_at=? WHERE id=?',
            (note, _now(), pool_id)
        )


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


# ── ΕΛΕΓΧΟΣ ΠΟΙΟΤΗΤΑΣ / STATUS ──────────────────────────────────────────────

def get_flagged_invoices():
    """Τιμολόγια με πιθανά προβλήματα δεδομένων, ένα πέρασμα πάνω σε όλα τα
    τιμολόγια — μικρό dataset σε αυτή την κλίμακα, δεν χρειάζεται caching.
    Σειρά προτεραιότητας ανά τιμολόγιο: διπλότυπο > σοβαρό > μέτριο.
    - διπλότυπο: ίδιο (doc_number, doc_date, supplier_id) με άλλο τιμολόγιο
      (ίδια λογική με το _find_duplicate(), εδώ ως group query).
    - σοβαρό: υπάρχει γραμμή με "[ΑΓΝΩΣΤΟ" στην περιγραφή (το placeholder
      μοτίβο για δυσανάγνωστες σαρώσεις), ή SUM(items.value) αποκλίνει από
      το net_amount πέρα από ό,τι θα μπορούσε να εξηγηθεί ως ΕΞΟΔΑ/μεταφορικά
      (>20€ ή >5% του net_amount — το ΕΞΟΔΑ δεν είναι δικό του πεδίο στη
      βάση, μόνο στο τυπωμένο χαρτί, οπότε αυτό είναι ευριστικό όριο).
    - μέτριο: μικρότερη αναντιστοιχία εντός του παραπάνω ορίου (πιθανό
      ΕΞΟΔΑ, μη επιβεβαιωμένο), ή γραμμή με ποσότητα αλλά χωρίς τιμή που δεν
      είναι γνωστή νόμιμη εξαίρεση (ΠΕΡΙΒ.ΕΙΣΦΟΡΑ, ή τιμολόγιο χωρίς
      net_amount συνολικά — price-less delivery note, αναμενόμενο)."""
    with get_db() as conn:
        invoices = conn.execute('''
            SELECT i.id, i.doc_number, i.doc_date, i.net_amount, s.name as supplier_name
            FROM tbl_invoices i
            LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
        ''').fetchall()

        dup_rows = conn.execute('''
            SELECT GROUP_CONCAT(id) as ids
            FROM tbl_invoices
            WHERE doc_number IS NOT NULL AND doc_number != ''
            GROUP BY doc_number, doc_date, supplier_id
            HAVING COUNT(*) > 1
        ''').fetchall()
        duplicate_ids = set()
        for r in dup_rows:
            duplicate_ids.update(int(x) for x in r['ids'].split(','))

        items_by_invoice = {}
        for it in conn.execute(
            'SELECT invoice_id, description, quantity, value FROM tbl_invoice_items'
        ).fetchall():
            items_by_invoice.setdefault(it['invoice_id'], []).append(it)

    flagged = []
    for inv in invoices:
        inv_id = inv['id']
        net_amount = inv['net_amount']
        items = items_by_invoice.get(inv_id, [])
        severity = None
        reason = None

        if inv_id in duplicate_ids:
            severity = 'duplicate'
            reason = 'Διπλότυπο (ίδιο doc_number/ημερομηνία/προμηθευτή)'
        else:
            has_unknown_line = any(
                it['description'] and '[ΑΓΝΩΣΤΟ' in it['description'] for it in items
            )
            diff = None
            if net_amount is not None:
                item_sum = sum(it['value'] for it in items if it['value'] is not None)
                diff = abs(item_sum - net_amount)

            if has_unknown_line:
                severity = 'severe'
                reason = 'Δυσανάγνωστη/άγνωστη γραμμή'
            elif diff is not None and diff > max(20.0, 0.05 * net_amount):
                severity = 'severe'
                reason = f'Αναντιστοιχία {diff:.2f}€ (γραμμές έναντι net_amount)'
            elif diff is not None and diff > 0.01:
                severity = 'moderate'
                reason = f'Μικρή αναντιστοιχία {diff:.2f}€ (πιθανό ΕΞΟΔΑ, μη επιβεβαιωμένο)'
            elif net_amount is not None:
                missing_value_line = any(
                    it['quantity'] is not None and it['value'] is None and
                    (not it['description'] or 'ΕΙΣΦΟΡΑ' not in it['description'])
                    for it in items
                )
                if missing_value_line:
                    severity = 'moderate'
                    reason = 'Γραμμή με ποσότητα χωρίς τιμή'

        if severity:
            flagged.append({
                'invoice_id': inv_id,
                'doc_number': inv['doc_number'],
                'doc_date': inv['doc_date'],
                'supplier_name': inv['supplier_name'],
                'net_amount': net_amount,
                'severity': severity,
                'reason': reason,
            })
    return flagged


def get_invoice_status_summary():
    with get_db() as conn:
        total_invoices = conn.execute('SELECT COUNT(*) as c FROM tbl_invoices').fetchone()['c']
        by_category = [dict(r) for r in conn.execute('''
            SELECT category, COUNT(DISTINCT invoice_id) as count
            FROM tbl_invoice_items
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category ORDER BY count DESC
        ''').fetchall()]
    flagged = get_flagged_invoices()
    return {
        'total_invoices': total_invoices,
        'by_category': by_category,
        'flagged_severe': sum(1 for f in flagged if f['severity'] == 'severe'),
        'flagged_moderate': sum(1 for f in flagged if f['severity'] == 'moderate'),
        'flagged_duplicate': sum(1 for f in flagged if f['severity'] == 'duplicate'),
    }
