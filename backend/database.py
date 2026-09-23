# -*- coding: utf-8 -*-
"""
database.py — SQLite access layer για το InvoiceBook.

DB_NAME ορίζεται δυναμικά από το bridge.py πριν κληθεί initialize_database().
"""
import sqlite3
import os
import re
import sys
import json
import shutil
import unicodedata
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone

DB_NAME = None       # ορίζεται από bridge.py
PDF_STORE_DIR = None  # ορίζεται από bridge.py — φάκελος όπου "υιοθετούνται" τα PDF

_local_db_dir = os.path.dirname(os.path.abspath(__file__ + '/../database'))
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'schema.sql')
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database')

CURRENT_SCHEMA_VERSION = 6

migration_files = {
    1: os.path.join(MIGRATIONS_DIR, 'migration_001_initial_schema.sql'),
    2: os.path.join(MIGRATIONS_DIR, 'migration_002_generalize_invoices.sql'),
    3: os.path.join(MIGRATIONS_DIR, 'migration_003_invoice_reviews.sql'),
    4: os.path.join(MIGRATIONS_DIR, 'migration_004_dismissed_merge_candidates.sql'),
    5: os.path.join(MIGRATIONS_DIR, 'migration_005_pdf_hashes.sql'),
    6: os.path.join(MIGRATIONS_DIR, 'migration_006_invoice_exports.sql'),
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


# ── ΑΠΟΡΡΙΦΘΕΝΤΑ (Παράβλεψη) MERGE CANDIDATES — κοινό σε suppliers/machines/description ──
# Το "Παράβλεψη" στο UI έδειχνε να δουλεύει αλλά ήταν καθαρά τοπικό στο DOM -- η
# επόμενη φόρτωση της λίστας ξανάβρισκε το ίδιο candidate, αφού καμία απόφαση δεν
# καταγραφόταν. Ίδιο σκεπτικό με tbl_invoice_reviews: ανθρώπινη απόφαση δεν πρέπει
# να χάνεται όταν η αυτόματη ανίχνευση ξανατρέξει.

def _load_dismissed_keys(kind):
    with get_db() as conn:
        rows = conn.execute(
            'SELECT candidate_key FROM tbl_dismissed_merge_candidates WHERE kind=?', (kind,)
        ).fetchall()
    return {r['candidate_key'] for r in rows}


def dismiss_merge_candidate(kind, candidate_key):
    with get_db() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO tbl_dismissed_merge_candidates (kind, candidate_key, dismissed_at) VALUES (?, ?, ?)',
            (kind, candidate_key, _now())
        )


# ── ΣΥΓΧΩΝΕΥΣΗ ΠΡΟΜΗΘΕΥΤΩΝ (dedup) ────────────────────────────────────────────

_SUPPLIER_NAME_STOPWORDS = {
    'αφοι', 'αφων', 'σια', 'υιοι', 'υιος', 'υιου', 'υιων',
    'ανωνυμη', 'εταιρια', 'εταιρειας', 'ομορρυθμη', 'ετερορρυθμη',
    'ιδιωτικη', 'κεφαλαιουχικη', 'περιορισμενης', 'ευθυνης', 'ike',
}


def _normalize_greek(s):
    # Ίδια λογική με το normalizeGreek() του js/import.js (intake-tool):
    # NFD + αφαίρεση διακριτικών + πεζά + τελικό ς -> σ, ώστε τα tokens να
    # ταιριάζουν ανεξάρτητα από τόνους/κεφαλαία.
    if not s:
        return ''
    decomposed = unicodedata.normalize('NFD', s)
    stripped = ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')
    return stripped.lower().replace('ς', 'σ').strip()


def _name_tokens(s):
    return {
        w for w in re.split(r'[^a-zα-ω0-9]+', _normalize_greek(s))
        if len(w) >= 3 and w not in _SUPPLIER_NAME_STOPWORDS
    }


def _vat_checksum_valid(vat):
    """Έλεγχος ψηφίου-ελέγχου ελληνικού ΑΦΜ (mod-11 -> mod-10 επί των πρώτων 8
    ψηφίων, το 9ο ψηφίο είναι το check digit). None αν το ΑΦΜ δεν είναι
    ελέγξιμο (λείπει/όχι ακριβώς 9 ψηφία), αλλιώς True/False."""
    if not vat or not re.fullmatch(r'\d{9}', vat):
        return None
    digits = [int(c) for c in vat]
    total = sum(d * (2 ** (8 - i)) for i, d in enumerate(digits[:8]))
    return (total % 11) % 10 == digits[8]


def _hamming_close_vat(a, b):
    if not a or not b or len(a) != len(b) or len(a) < 8:
        return False
    diff = sum(1 for x, y in zip(a, b) if x != y)
    return 0 < diff <= 2


def get_supplier_merge_candidates():
    """Υποψήφιοι προς συγχώνευση προμηθευτές, σε δύο βαθμίδες εμπιστοσύνης:
    STRONG (κοντινά ΑΦΜ όπου το checksum λύνει ποιο είναι σωστό, ΚΑΙ επιπλέον
    υπάρχει έστω κι ελάχιστη ομοιότητα ονόματος) και MEDIUM (επικάλυψη
    ονόματος μόνο, μετά από φιλτράρισμα κοινών tokens).

    Σκόπιμα ΔΕΝ αρκεί μόνο του το ΑΦΜ-hamming-closeness+checksum για STRONG:
    τα ΑΦΜ απονέμονται περίπου διαδοχικά από την εφορία, άσχετα με το όνομα
    της επιχείρησης — δύο εντελώς άσχετοι προμηθευτές μπορεί να έχουν τυχαία
    ΑΦΜ που διαφέρουν κατά 1-2 ψηφία (επιβεβαιώθηκε στην πράξη σε δοκιμή πάνω
    σε αντίγραφο της πραγματικής βάσης — δύο εντελώς διαφορετικές επωνυμίες
    βγήκαν σαν "STRONG" πριν προστεθεί αυτός ο περιορισμός). Το checksum
    χρησιμεύει ΜΟΝΟ για να λύσει ΠΟΙΟ από δύο ήδη-υποψήφια (λόγω ονόματος)
    ΑΦΜ είναι το σωστό — ίδια χρήση με το πώς δούλεψε διαδραστικά με τον
    χρήστη στο χειροκίνητο sweep του 2026-09-05."""
    suppliers = get_all_suppliers()

    name_freq = {}
    tokens_by_id = {}
    for s in suppliers:
        toks = _name_tokens(s['name'])
        tokens_by_id[s['id']] = toks
        for t in toks:
            name_freq[t] = name_freq.get(t, 0) + 1
    # tokens που εμφανίζονται σε >3 προμηθευτές είναι πολύ γενικά (μικρά
    # ονόματα/οικογενειακοί όροι) για να μετράνε σαν σήμα ομοιότητας.
    common_tokens = {t for t, c in name_freq.items() if c > 3}

    candidates = []
    for i, a in enumerate(suppliers):
        for b in suppliers[i + 1:]:
            toks_a = tokens_by_id[a['id']] - common_tokens
            toks_b = tokens_by_id[b['id']] - common_tokens
            overlap = toks_a & toks_b
            min_size = min(len(toks_a), len(toks_b))
            name_match = bool(overlap) and (len(overlap) >= 2 or (len(overlap) == 1 and min_size <= 1))

            vat_resolved = None
            a_vat, b_vat = a.get('vat_number'), b.get('vat_number')
            if a_vat and b_vat and _hamming_close_vat(a_vat, b_vat):
                a_valid = _vat_checksum_valid(a_vat)
                b_valid = _vat_checksum_valid(b_vat)
                if a_valid is True and b_valid is False:
                    vat_resolved = (a, b, a_vat)
                elif b_valid is True and a_valid is False:
                    vat_resolved = (b, a, b_vat)

            if vat_resolved and overlap:
                keep, merge, vat = vat_resolved
                candidates.append(_merge_candidate(keep, merge, 'STRONG',
                    f'ΑΦΜ διαφέρει λίγα ψηφία (checksum επιβεβαιώνει {vat}) '
                    f'+ κοινά tokens ονόματος: {", ".join(sorted(overlap))}'))
            elif name_match:
                # Ο προμηθευτής με το μεγαλύτερο id θεωρείται πιο πρόσφατος·
                # προτείνεται σαν "προς συγχώνευση" απλά ως προεπιλογή — ο
                # χρήστης μπορεί να αντιστρέψει κατεύθυνση στο UI.
                keep, merge = (a, b) if a['id'] < b['id'] else (b, a)
                candidates.append(_merge_candidate(keep, merge, 'MEDIUM',
                    f'κοινά tokens ονόματος: {", ".join(sorted(overlap))}'))

    dismissed = _load_dismissed_keys('supplier')
    candidates = [c for c in candidates if c['dismiss_key'] not in dismissed]

    tier_order = {'STRONG': 0, 'MEDIUM': 1}
    candidates.sort(key=lambda c: tier_order[c['tier']])
    return candidates


def _merge_candidate(keep, merge, tier, reason):
    return {
        'keep_id': keep['id'], 'keep_name': keep['name'], 'keep_vat': keep.get('vat_number'),
        'merge_id': merge['id'], 'merge_name': merge['name'], 'merge_vat': merge.get('vat_number'),
        'tier': tier, 'reason': reason,
        'dismiss_key': f"{keep['id']}:{merge['id']}",
    }


def get_supplier_merge_preview(keep_id, merge_id):
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id, doc_number, doc_date, total_amount FROM tbl_invoices '
            'WHERE supplier_id=? ORDER BY doc_date', (merge_id,)
        ).fetchall()
    return {'invoice_count': len(rows), 'invoices': [dict(r) for r in rows]}


def merge_suppliers(keep_id, merge_id):
    if keep_id == merge_id:
        raise ValueError('Δεν μπορεί να συγχωνευτεί προμηθευτής με τον εαυτό του')
    with get_db() as conn:
        cur = conn.execute(
            'UPDATE tbl_invoices SET supplier_id=? WHERE supplier_id=?',
            (keep_id, merge_id)
        )
        reassigned = cur.rowcount
        conn.execute('DELETE FROM tbl_suppliers WHERE id=?', (merge_id,))
    return {'reassigned_invoices': reassigned}


def get_description_merge_candidates():
    """Ομάδες περιγραφών (tbl_invoice_items.description) που κανονικοποιούνται στο ίδιο
    κλειδί μέσω _normalize_machine_code — ΙΔΙΑ λογική με _canonicalize_description, που
    ήδη εμποδίζει νέα διπλότυπα στο write path. Εδώ βρίσκουμε clusters σε ΗΔΗ υπάρχοντα
    δεδομένα. Ομαδοποίηση με hash σε (category, normalized_code) — O(n), όχι pairwise
    (5.382 distinct descriptions θα ήταν ~14.5M ζεύγη pairwise, πολύ ακριβό)."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT category, description, COUNT(*) as cnt FROM tbl_invoice_items '
            'WHERE category IS NOT NULL AND description IS NOT NULL '
            'GROUP BY category, description'
        ).fetchall()

    groups = {}
    for r in rows:
        norm = _normalize_machine_code(r['description'])
        if not norm or len(norm) < 3:
            continue
        groups.setdefault((r['category'], norm), []).append(
            {'description': r['description'], 'count': r['cnt']}
        )

    dismissed = _load_dismissed_keys('description')
    candidates = []
    for (category, norm), variants in groups.items():
        if len(variants) < 2:
            continue
        variants.sort(key=lambda v: -v['count'])
        keep, rest = variants[0], variants[1:]
        others = []
        for v in rest:
            key = _description_dismiss_key(category, keep['description'], v['description'])
            if key in dismissed:
                continue
            others.append({**v, 'dismiss_key': key})
        if not others:
            continue
        candidates.append({
            'category': category,
            'keep': keep['description'], 'keep_count': keep['count'],
            'variants': others,
            'affected_rows': sum(v['count'] for v in others),
        })
    candidates.sort(key=lambda c: -c['affected_rows'])
    return candidates


def _description_dismiss_key(category, keep, variant):
    # Hash αντί για απλό join -- η περιγραφή είναι ελεύθερο κείμενο, μπορεί να
    # περιέχει οποιονδήποτε χαρακτήρα (ασφαλές διαχωριστικό ΔΕΝ εγγυάται μοναδικότητα).
    raw = f'{category}\x1f{keep}\x1f{variant}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def merge_item_descriptions(category, keep, merge_list):
    if not merge_list:
        raise ValueError('Καμία τιμή προς συγχώνευση')
    with get_db() as conn:
        total = 0
        for m in merge_list:
            if m == keep:
                continue
            cur = conn.execute(
                'UPDATE tbl_invoice_items SET description=? WHERE category=? AND description=?',
                (keep, category, m)
            )
            total += cur.rowcount
    return {'updated_rows': total}


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
            (invoice_id, it.get('code'), it.get('description') or '', canonical_unit(it.get('unit')),
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
    ήδη υπάρχον native UI του invoicebook).

    source_pdf_filename: αν το header ΔΕΝ έχει καθόλου το κλειδί, κρατιέται το
    υπάρχον -- το native invoice form του invoicebook δεν το στέλνει, και πριν
    κάθε αποθήκευση από εκεί μηδένιζε σιωπηλά τη σύνδεση (το αρχείο έμενε ορφανό
    στο pdf_store). Ρητό None (π.χ. _resolve_header) συνεχίζει να σημαίνει «χωρίς PDF»."""
    with get_db() as conn:
        if 'source_pdf_filename' not in header:
            row = conn.execute('SELECT source_pdf_filename FROM tbl_invoices WHERE id=?', (invoice_id,)).fetchone()
            header = {**header, 'source_pdf_filename': row['source_pdf_filename'] if row else None}
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
                    (it.get('code'), it.get('description') or '', canonical_unit(it.get('unit')), it.get('quantity'),
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
                    (invoice_id, it.get('code'), it.get('description') or '', canonical_unit(it.get('unit')),
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
    κι αυτό είναι πραγματικό ιστορικό κατανάλωσης, όχι απλά staging data.

    Σβήνει ΚΑΙ το PDF του από το pdf_store (μετά το commit), εκτός αν το ίδιο
    αρχείο το χρησιμοποιεί κι άλλο τιμολόγιο -- πριν έμενε ορφανό σε κάθε
    διαγραφή (βλ. 3 ορφανά 2026-09-23)."""
    with get_db() as conn:
        row = conn.execute('SELECT source_pdf_filename FROM tbl_invoices WHERE id=?', (invoice_id,)).fetchone()
        pdf_filename = row['source_pdf_filename'] if row else None
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
    return {'pdf_deleted': pdf_filename if _remove_stored_pdf_if_unreferenced(pdf_filename) else None}


def delete_invoice_item(item_id):
    """Διαγράφει ΜΙΑ γραμμή τιμολογίου (όχι όλο το τιμολόγιο) — π.χ. όταν μια
    γραμμή αποδεικνύεται εντελώς λάθος/διπλή κατά τη διόρθωση, όχι απλά με
    λάθος τιμές. Ίδιος έλεγχος ασφαλείας με το delete_invoice: μπλοκάρει αν η
    γραμμή έχει ήδη bulk διαμοιρασμό σε μηχανήματα."""
    with get_db() as conn:
        alloc_count = conn.execute(
            '''SELECT COUNT(*) FROM tbl_allocations a
               JOIN tbl_bulk_pools p ON p.id = a.pool_id
               WHERE p.invoice_item_id = ?''', (item_id,)
        ).fetchone()[0]
        if alloc_count:
            raise ValueError(
                f'Δεν διαγράφεται — υπάρχουν {alloc_count} καταχωρημένοι διαμοιρασμοί σε '
                f'μηχανήματα πάνω σε αυτή τη bulk γραμμή. Αναίρεσε πρώτα τους διαμοιρασμούς '
                f'(tab Αποθέματα προς Διαμοιρασμό) αν πραγματικά χρειάζεται διαγραφή.'
            )
        conn.execute('DELETE FROM tbl_invoice_items WHERE id=?', (item_id,))


def split_invoice_item(item_id, splits):
    """Διασπά μία γραμμή τιμολογίου σε πολλές (π.χ. 4 τεμάχια φίλτρου που πήγαν σε 2
    διαφορετικά μηχανήματα, 2+2) — `splits` = [{'machine_name', 'quantity', 'value'}, ...],
    μήκους >=2. Πριν αγγιχτεί η βάση, απορρίπτει αν sum(quantity)/sum(value) δεν
    ταιριάζουν ΑΚΡΙΒΩΣ (μικρή float ανοχή) με την αρχική γραμμή -- πραγματικό bug που
    βρέθηκε χειροκίνητα σε ένα από τα 3 πρώτα split (invoice 1306, "U12+", 2026-09-17):
    ξεχάστηκε να μειωθεί η αρχική ποσότητα/αξία, το άθροισμα δεν ταίριαζε πια με το
    header total, εντοπίστηκε μόνο αργότερα από reconciliation check. Το πρώτο split
    γίνεται UPDATE στην ΙΔΙΑ γραμμή (id σταθερό, ίδιο σκεπτικό με το update_invoice's
    "preserves item ids on purpose") -- τα υπόλοιπα INSERT νέων γραμμών, αντιγράφοντας
    code/description/unit/vat_pct/category/efk_eligible από την αρχική."""
    if len(splits) < 2:
        raise ValueError('Χρειάζονται τουλάχιστον 2 διαχωρισμοί για split')

    with get_db() as conn:
        item = conn.execute('SELECT * FROM tbl_invoice_items WHERE id=?', (item_id,)).fetchone()
        if not item:
            raise ValueError(f'Δεν βρέθηκε γραμμή id={item_id}')

        pool = conn.execute(
            'SELECT id FROM tbl_bulk_pools WHERE invoice_item_id=?', (item_id,)
        ).fetchone()
        if pool:
            raise ValueError(
                'Δεν διασπάται -- αυτή η γραμμή είναι bulk/έχει ήδη διαμοιρασμό. '
                'Χρησιμοποίησε το tab Αποθέματα προς Διαμοιρασμό αντ\' αυτού.'
            )

        total_qty = sum(s['quantity'] for s in splits)
        total_val = sum(s['value'] for s in splits)
        if item['quantity'] is not None and abs(total_qty - item['quantity']) > 0.001:
            raise ValueError(
                f'Το άθροισμα ποσοτήτων ({total_qty}) δεν ταιριάζει με την αρχική '
                f'ποσότητα ({item["quantity"]})'
            )
        if item['value'] is not None and abs(total_val - item['value']) > 0.01:
            raise ValueError(
                f'Το άθροισμα αξιών ({total_val}) δεν ταιριάζει με την αρχική '
                f'αξία ({item["value"]})'
            )

        new_ids = [item_id]
        first = splits[0]
        machine_id0 = _find_or_create_machine(conn, first.get('machine_name'))
        unit_price0 = (first['value'] / first['quantity']) if first['quantity'] else None
        conn.execute(
            'UPDATE tbl_invoice_items SET quantity=?, unit_price=?, value=?, machine_id=? WHERE id=?',
            (first['quantity'], unit_price0, first['value'], machine_id0, item_id)
        )
        for s in splits[1:]:
            machine_id = _find_or_create_machine(conn, s.get('machine_name'))
            unit_price = (s['value'] / s['quantity']) if s['quantity'] else None
            cur = conn.execute(
                '''INSERT INTO tbl_invoice_items
                   (invoice_id, code, description, unit, quantity, unit_price, value, vat_pct,
                    category, machine_id, efk_eligible)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (item['invoice_id'], item['code'], item['description'], item['unit'],
                 s['quantity'], unit_price, s['value'], item['vat_pct'],
                 item['category'], machine_id, item['efk_eligible'])
            )
            new_ids.append(cur.lastrowid)

        return {'ok': True, 'item_ids': new_ids}


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


def _same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _in_pdf_store(path):
    return _same_path(os.path.dirname(os.path.abspath(path)), PDF_STORE_DIR)


def _remove_stored_pdf_if_unreferenced(filename):
    """Σβήνει ένα αρχείο του pdf_store ΜΟΝΟ αν κανένα τιμολόγιο δεν το αναφέρει.
    Επιστρέφει True αν σβήστηκε."""
    if not filename or not PDF_STORE_DIR or os.path.basename(filename) != filename:
        return False
    with get_db() as conn:
        if conn.execute('SELECT 1 FROM tbl_invoices WHERE source_pdf_filename=? LIMIT 1', (filename,)).fetchone():
            return False
        conn.execute('DELETE FROM tbl_pdf_hashes WHERE filename=?', (filename,))
    path = os.path.join(PDF_STORE_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def attach_pdf(invoice_id, source_path):
    """Επισυνάπτει/αντικαθιστά το PDF ενός τιμολογίου στο pdf_store, με όνομα από
    το _build_pdf_filename. Τρεις περιπτώσεις που πριν άφηναν ορφανά/λάθος ονόματα
    (βλ. Τριαντόπουλος 904, 2026-09-23):
    - Αντικατάσταση: το ΠΡΟΗΓΟΥΜΕΝΟ αρχείο του τιμολογίου σβήνεται (αν δεν το
      χρησιμοποιεί άλλο τιμολόγιο) και δεν «πιάνει» το τελικό όνομα -> όχι "(2)".
    - Πηγή ήδη μέσα στο pdf_store (π.χ. ορφανό αρχείο): μετονομάζεται στη θέση
      του, δεν μετράει ως σύγκρουση με τον εαυτό του -> όχι "(3)".
    - Πηγή που είναι το PDF ΑΛΛΟΥ τιμολογίου: αντιγράφεται, δεν μετακινείται
      (αλλιώς θα έμενε εκείνο χωρίς αρχείο)."""
    if not PDF_STORE_DIR:
        raise RuntimeError('PDF_STORE_DIR δεν έχει οριστεί')
    if not os.path.isfile(source_path):
        raise ValueError(f'Το αρχείο δεν βρέθηκε: {source_path}')
    os.makedirs(PDF_STORE_DIR, exist_ok=True)

    with get_db() as conn:
        row = conn.execute('SELECT source_pdf_filename FROM tbl_invoices WHERE id=?', (invoice_id,)).fetchone()
        if not row:
            raise ValueError('Το τιμολόγιο δεν βρέθηκε')
        old_filename = row['source_pdf_filename']
        filename = _build_pdf_filename(conn, invoice_id)
        src_name = os.path.basename(source_path) if _in_pdf_store(source_path) else None
        src_used_by_other = bool(src_name) and conn.execute(
            'SELECT 1 FROM tbl_invoices WHERE source_pdf_filename=? AND id<>? LIMIT 1', (src_name, invoice_id)
        ).fetchone() is not None
        old_used_by_other = bool(old_filename) and conn.execute(
            'SELECT 1 FROM tbl_invoices WHERE source_pdf_filename=? AND id<>? LIMIT 1', (old_filename, invoice_id)
        ).fetchone() is not None

    # Η πηγή περνάει πρώτα από προσωρινό όνομα, ώστε ούτε η ίδια ούτε το παλιό αρχείο
    # να «πιάνουν» το τελικό όνομα κατά την επιλογή του.
    tmp_path = os.path.join(PDF_STORE_DIR, f'_attach_tmp_{invoice_id}.pdf')
    if src_used_by_other:
        shutil.copy2(source_path, tmp_path)
    else:
        shutil.move(source_path, tmp_path)

    try:
        old_path = os.path.join(PDF_STORE_DIR, old_filename) if old_filename else None
        stem, ext = os.path.splitext(filename)
        dest_path = os.path.join(PDF_STORE_DIR, filename)
        counter = 2
        # Το παλιό αρχείο του ΙΔΙΟΥ τιμολογίου δεν είναι σύγκρουση -- αντικαθίσταται.
        # (Μια πηγή που ήταν ήδη στο canonical όνομά της -- π.χ. ορφανό PDF, 2026-09-21 --
        # βρίσκεται πλέον στο tmp_path, οπότε δεν «πιάνει» το όνομα ούτε αυτή.)
        while os.path.exists(dest_path) and not (
                old_path and not old_used_by_other and _same_path(dest_path, old_path)):
            dest_path = os.path.join(PDF_STORE_DIR, f'{stem} ({counter}){ext}')
            counter += 1
        os.replace(tmp_path, dest_path)
    except Exception:
        if not src_used_by_other and os.path.exists(tmp_path) and not os.path.exists(source_path):
            shutil.move(tmp_path, source_path)
        raise
    stored_name = os.path.basename(dest_path)

    with get_db() as conn:
        conn.execute(
            'UPDATE tbl_invoices SET source_pdf_filename=?, updated_at=? WHERE id=?',
            (stored_name, _now(), invoice_id)
        )
        conn.execute('DELETE FROM tbl_pdf_hashes WHERE filename=?', (stored_name,))
    if old_filename and old_filename != stored_name:
        _remove_stored_pdf_if_unreferenced(old_filename)
    return stored_name


# ── ΜΟΝΑΔΕΣ ΜΕΤΡΗΣΗΣ: κανονικό σύνολο + ενοποίηση παραλλαγών ──────────────────
# Το IMPORT_PROMPT ζητάει μόνο L / kg / ΤΕΜ (ελληνικά) / m, αλλά στην πράξη μπήκαν και
# οπτικά ίδιες παραλλαγές με διαφορετικούς χαρακτήρες (321 γραμμές «TEM» με λατινικά,
# imports 29/8–15/9, «KG», «Μ» ελληνικό) — χωρίζουν κάθε άθροισμα/φίλτρο ανά μονάδα στα δύο.
# canonical_unit() τρέχει σε ΚΑΘΕ εγγραφή γραμμής, ώστε να μην ξαναμπαίνουν· οι ήδη
# υπάρχουσες ενοποιούνται από το εργαλείο «Μονάδες» (get_unit_variants/merge_units).
CANONICAL_UNITS = ('L', 'kg', 'ΤΕΜ', 'm')

# Κλειδί: κεφαλαία, χωρίς τόνους/τελείες/κενά, ελληνικά ομοιόμορφα → λατινικά (ίδιο
# _GREEK_LATIN_HOMOGLYPHS με τα μηχανήματα), ώστε «ΤΕΜ»/«TEM»/«τεμ.» να δίνουν το ίδιο.
_UNIT_ALIASES = {
    'L': 'L', 'LT': 'L', 'LTR': 'L', 'LTRS': 'L', 'LITRE': 'L', 'LITER': 'L',
    'ΛIT': 'L', 'ΛITPA': 'L', 'ΛITPO': 'L', 'ΛT': 'L',
    'KG': 'kg', 'KGS': 'kg', 'KIΛ': 'kg', 'KIΛA': 'kg', 'KIΛO': 'kg', 'KΓ': 'kg',
    'TEM': 'ΤΕΜ', 'TEMAXIA': 'ΤΕΜ', 'TEMAXIO': 'ΤΕΜ', 'TMX': 'ΤΕΜ', 'PCS': 'ΤΕΜ', 'PC': 'ΤΕΜ',
    'M': 'm', 'MET': 'm', 'METP': 'm', 'METPA': 'm', 'METPO': 'm', 'MTP': 'm',
}


def _unit_key(unit):
    u = unicodedata.normalize('NFD', unit or '')
    u = ''.join(c for c in u if unicodedata.category(c) != 'Mn').upper()
    return re.sub(r'[.\s]', '', u).translate(_GREEK_LATIN_HOMOGLYPHS)


def canonical_unit(unit):
    """Η κανονική μορφή μιας γνωστής παραλλαγής (TEM→ΤΕΜ, KG→kg, Μ→m)· άγνωστη μονάδα
    (π.χ. m3) μένει όπως ήρθε, κενή → None."""
    if unit is None or not str(unit).strip():
        return None
    unit = str(unit).strip()
    if unit in CANONICAL_UNITS:
        return unit
    return _UNIT_ALIASES.get(_unit_key(unit), unit)


def _unit_script(unit):
    has_latin = bool(re.search(r'[A-Za-z]', unit))
    has_greek = bool(re.search(r'[Α-Ωα-ωΆ-Ώά-ώ]', unit))
    return 'μικτά' if has_latin and has_greek else 'λατινικά' if has_latin else 'ελληνικά' if has_greek else ''


def get_unit_variants():
    """Μονάδες εκτός του κανονικού συνόλου, με πλήθος γραμμών, προτεινόμενη κανονική
    (αν είναι γνωστή παραλλαγή) και σε ποιες κατηγορίες εμφανίζονται. Όχι όσες έχουν
    «Παράβλεψη» (kind 'unit', key = η ίδια η μονάδα)."""
    dismissed = _load_dismissed_keys('unit')
    with get_db() as conn:
        rows = conn.execute(
            """SELECT unit, COUNT(*) AS n, GROUP_CONCAT(DISTINCT COALESCE(category, '—')) AS cats
               FROM tbl_invoice_items WHERE unit IS NOT NULL AND TRIM(unit) <> ''
               GROUP BY unit ORDER BY n DESC"""
        ).fetchall()
    out = []
    for r in rows:
        if r['unit'] in CANONICAL_UNITS or r['unit'] in dismissed:
            continue
        suggested = canonical_unit(r['unit'])
        out.append({
            'unit': r['unit'], 'count': r['n'], 'script': _unit_script(r['unit']),
            'suggested': suggested if suggested in CANONICAL_UNITS else None,
            'categories': (r['cats'] or '').split(','), 'dismiss_key': r['unit'],
        })
    return out


def merge_units(from_unit, to_unit):
    """Όλες οι γραμμές (και τα αποθέματα προς διαμοιρασμό) με μονάδα from_unit → to_unit.
    Μόνο προς κανονική μονάδα — αλλιώς θα δημιουργούσε νέα παραλλαγή."""
    if to_unit not in CANONICAL_UNITS:
        raise ValueError(f'Η μονάδα-στόχος πρέπει να είναι μία από: {", ".join(CANONICAL_UNITS)}')
    if from_unit == to_unit:
        raise ValueError('Ίδια μονάδα')
    with get_db() as conn:
        items = conn.execute('UPDATE tbl_invoice_items SET unit=? WHERE unit=?', (to_unit, from_unit)).rowcount
        pools = conn.execute('UPDATE tbl_bulk_pools SET unit=? WHERE unit=?', (to_unit, from_unit)).rowcount
    return {'items': items, 'pools': pools}


# ── ΙΣΤΟΡΙΚΟ ΕΞΑΓΩΓΩΝ προς εξωτερικά συστήματα (γενικό, target = σύστημα) ──────

def record_invoice_exports(target, invoice_ids, file_name=None):
    now = _now()
    with get_db() as conn:
        conn.executemany(
            'INSERT INTO tbl_invoice_exports (invoice_id, target, exported_at, file_name) VALUES (?, ?, ?, ?)',
            [(int(i), target, now, file_name) for i in invoice_ids]
        )
    return now


def get_invoice_exports(target):
    """{invoice_id: {'exported_at', 'file_name', 'count'}} -- η ΤΕΛΕΥΤΑΙΑ εξαγωγή κάθε
    τιμολογίου προς το target, και πόσες φορές έχει εξαχθεί συνολικά."""
    with get_db() as conn:
        rows = conn.execute(
            '''SELECT invoice_id, exported_at, file_name FROM tbl_invoice_exports
               WHERE target=? ORDER BY exported_at, id''', (target,)
        ).fetchall()
    out = {}
    for r in rows:
        prev = out.get(r['invoice_id'], {'count': 0})
        out[r['invoice_id']] = {'exported_at': r['exported_at'], 'file_name': r['file_name'],
                                'count': prev['count'] + 1}
    return out


# ── ΑΡΧΕΙΑ PDF: ορφανά / χαμένα / ίδιο PDF σε πολλά τιμολόγια (Layer 1 dedup) ──
# Layer 1 = ίδιο ΑΚΡΙΒΩΣ αρχείο (SHA256), συμπληρωματικό του Layer 2 (_find_duplicate:
# αρ. παραστατικού+ημερομηνία+προμηθευτής), που χάνει διπλοκαταχωρήσεις όταν το OCR
# διαβάσει διαφορετικά τον αριθμό (βρέθηκαν 3 τέτοιες 2026-09-23, π.χ. «236»/«Κ2 236»).
# ΔΕΝ πιάνει ξανα-σαρώσεις του ίδιου χαρτιού (διαφορετικά bytes). Hash μόνο για αρχεία
# που μοιράζονται μέγεθος με κάποιο άλλο -- ίδιο περιεχόμενο => ίδιο μέγεθος, οπότε τα
# περισσότερα αρχεία δεν χρειάζεται καν να διαβαστούν.

_PDF_TMP_PREFIXES = ('_merge_tmp_', '_attach_tmp_')


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _store_pdf_files():
    """{filename: (size, mtime)} για τα PDF του pdf_store (χωρίς προσωρινά)."""
    if not PDF_STORE_DIR or not os.path.isdir(PDF_STORE_DIR):
        return {}
    files = {}
    for entry in os.scandir(PDF_STORE_DIR):
        if (entry.is_file() and entry.name.lower().endswith('.pdf')
                and not entry.name.startswith(_PDF_TMP_PREFIXES)):
            st = entry.stat()
            files[entry.name] = (st.st_size, st.st_mtime)
    return files


def _cached_hashes(conn, files, names):
    """sha256 για τα names (αρχεία του pdf_store), μέσω tbl_pdf_hashes -- ξαναδιαβάζει
    ένα αρχείο μόνο αν άλλαξε μέγεθος/mtime."""
    cache = {r['filename']: r for r in conn.execute('SELECT * FROM tbl_pdf_hashes').fetchall()}
    out = {}
    for name in names:
        size, mtime = files[name]
        c = cache.get(name)
        if c and c['size'] == size and c['mtime'] == mtime:
            out[name] = c['sha256']
            continue
        sha = _sha256_file(os.path.join(PDF_STORE_DIR, name))
        conn.execute('INSERT OR REPLACE INTO tbl_pdf_hashes (filename, size, mtime, sha256) VALUES (?, ?, ?, ?)',
                     (name, size, mtime, sha))
        out[name] = sha
    return out


def _invoice_pdf_refs(conn):
    rows = conn.execute(
        """SELECT i.id, i.doc_date, i.doc_number, i.total_amount, i.source_pdf_filename,
                  s.name as supplier_name
           FROM tbl_invoices i LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
           WHERE i.source_pdf_filename IS NOT NULL AND i.source_pdf_filename <> ''
           ORDER BY i.doc_date, i.id"""
    ).fetchall()
    refs = {}
    for r in rows:
        refs.setdefault(r['source_pdf_filename'], []).append(dict(r))
    return refs


def get_pdf_store_report():
    """Ορφανά αρχεία (κανένα τιμολόγιο δεν τα αναφέρει), τιμολόγια με PDF που λείπει,
    και ομάδες τιμολογίων με ΙΔΙΟ ακριβώς PDF (όχι όσες έχουν «Παράβλεψη»)."""
    files = _store_pdf_files()
    dismissed = _load_dismissed_keys('pdf')
    with get_db() as conn:
        refs = _invoice_pdf_refs(conn)
        by_size = {}
        for name, (size, _) in files.items():
            by_size.setdefault(size, []).append(name)
        to_hash = [n for group in by_size.values() if len(group) > 1 for n in group]
        hashes = _cached_hashes(conn, files, to_hash)
        # καθάρισμα cache από αρχεία που δεν υπάρχουν πια
        for (name,) in conn.execute('SELECT filename FROM tbl_pdf_hashes').fetchall():
            if name not in files:
                conn.execute('DELETE FROM tbl_pdf_hashes WHERE filename=?', (name,))

    existing_refs = [f for f in refs if f in files]
    by_hash = {}
    for name in existing_refs:
        if name in hashes:
            by_hash.setdefault(hashes[name], []).append(name)

    orphans = []
    for name in sorted(set(files) - set(refs)):
        same = by_hash.get(hashes.get(name), [])
        orphans.append({
            'filename': name, 'size': files[name][0], 'mtime': files[name][1],
            # ίδιο περιεχόμενο με το PDF κάποιου τιμολογίου -> ασφαλές να σβηστεί
            'same_as_invoices': [inv for f in same for inv in refs[f]],
        })

    missing = [inv for f in sorted(set(refs) - set(files)) for inv in refs[f]]

    duplicates = []
    for sha, names in by_hash.items():
        invoices = [inv for f in names for inv in refs[f]]
        if len(invoices) > 1 and sha not in dismissed:
            duplicates.append({'dismiss_key': sha, 'invoices': invoices})
    # Πολλά τιμολόγια στο ΙΔΙΟ όνομα αρχείου με μοναδικό μέγεθος (χωρίς hash) --
    # επίσης «ίδιο PDF».
    for name in existing_refs:
        if name not in hashes and len(refs[name]) > 1 and f'name:{name}' not in dismissed:
            duplicates.append({'dismiss_key': f'name:{name}', 'invoices': refs[name]})
    duplicates.sort(key=lambda g: g['invoices'][0]['doc_date'] or '')

    return {'total_files': len(files), 'orphans': orphans, 'missing': missing, 'duplicates': duplicates}


def delete_orphan_pdfs(filenames):
    """Σβήνει ΜΟΝΟ όσα από τα filenames είναι ακόμα ορφανά τη στιγμή της διαγραφής."""
    deleted = [f for f in filenames if _remove_stored_pdf_if_unreferenced(f)]
    return {'deleted': len(deleted), 'skipped': len(filenames) - len(deleted)}


def find_invoices_with_same_pdf(paths):
    """Layer 1 έλεγχος πριν την καταχώρηση: τιμολόγια των οποίων το PDF είναι ΙΔΙΟ
    ακριβώς αρχείο με κάποιο από τα paths (source_pdf_path ενός staging row --
    string ή λίστα σελίδων)."""
    if isinstance(paths, str):
        paths = [paths]
    paths = [p for p in (paths or []) if p and os.path.isfile(p)]
    if not paths:
        return []
    files = _store_pdf_files()
    matches = []
    with get_db() as conn:
        refs = _invoice_pdf_refs(conn)
        for p in paths:
            size = os.path.getsize(p)
            candidates = [n for n in refs if n in files and files[n][0] == size]
            if not candidates:
                continue
            sha = _sha256_file(p)
            hashes = _cached_hashes(conn, files, candidates)
            for name in candidates:
                if hashes[name] == sha:
                    matches.extend(dict(inv, matched_path=p) for inv in refs[name])
    return matches


def get_invoice_items_by_category(category=None, date_from=None, date_to=None):
    """Μία γραμμή ανά αποτέλεσμα (item), με τα header πεδία του τιμολογίου του
    "flattened" πάνω — ισοδύναμο του πρώην fuel domain's list_invoices(), αλλά σε
    επίπεδο γραμμής (ένα τιμολόγιο μπορεί να συνεισφέρει 0, 1 ή πολλές γραμμές
    στην ίδια κατηγορία). Χρησιμοποιείται από τα tabs Καύσιμα/Επισκευές/... του
    intake-tool για αναζήτηση/περιήγηση/διόρθωση ανά κατηγορία. category=None
    (ή κενό) = καμία στήλωση κατηγορίας — "Όλες" στο UI.
    LEFT JOIN (όχι JOIN) στα items: ένα confirmed τιμολόγιο μπορεί νόμιμα να
    έχει 0 γραμμές (π.χ. staging χωρίς αναγνώσιμο περιεχόμενο, βλ. #9870
    2026-08-26) — με INNER JOIN ένα τέτοιο τιμολόγιο ήταν μόνιμα αόρατο σε
    αυτή τη λίστα παρόλο που υπήρχε κανονικά στη βάση."""
    with get_db() as conn:
        q = '''SELECT it.id as item_id, it.code, it.description, it.unit, it.quantity,
                      it.unit_price, it.value, it.vat_pct, it.category, it.machine_id,
                      it.efk_eligible, m.name as machine_name,
                      i.id as invoice_id, i.doc_type, i.doc_number, i.doc_date, i.doc_time,
                      i.customer_name, i.customer_vat, i.customer_doy, i.customer_address,
                      i.customer_phone, i.net_amount, i.vat_amount, i.total_amount,
                      i.payment_method, i.notes, i.source_pdf_filename,
                      s.name as supplier_name, s.vat_number as supplier_vat
               FROM tbl_invoices i
               LEFT JOIN tbl_invoice_items it ON it.invoice_id = i.id
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


# Ελληνικά κεφαλαία γράμματα οπτικά πανομοιότυπα με λατινικά (π.χ. πληκτρολόγιο
# σε ελληνικά διάταξη κατά την πληκτρολόγηση πινακίδας μηχανήματος) -- χωρίς
# αυτό, "NHY 7148" (λατινικά) και "ΝΗΥ 7148" (ελληνικά, ίδια εμφάνιση) γίνονται
# δύο ξεχωριστές εγγραφές στο tbl_machines (βλ. dedup sweep, 111 εγγραφές αντί
# για τις πραγματικές μηχανές).
_GREEK_LATIN_HOMOGLYPHS = str.maketrans({
    'Α': 'A', 'Β': 'B', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'H', 'Ι': 'I', 'Κ': 'K',
    'Μ': 'M', 'Ν': 'N', 'Ο': 'O', 'Ρ': 'P', 'Τ': 'T', 'Υ': 'Y', 'Χ': 'X',
})


def _normalize_machine_code(name):
    """Κωδικός μηχανήματος χωρίς μορφοποίηση (κενά/παύλες/παρενθέσεις) και χωρίς
    διάκριση Ελληνικών/Λατινικών ομοιόμορφων γραμμάτων, ώστε "NHY 7148",
    "NHY-7148", "NHY7148", "ΝΗΥ 7148", "ΝΗΥ7148" να αναγνωρίζονται ως το ΙΔΙΟ
    μηχάνημα. Σκόπιμα ΔΕΝ πιάνει γράμματα που απλώς μοιάζουν οπτικά χωρίς να
    είναι το ίδιο γράμμα σε άλλο αλφάβητο (π.χ. "ΝΠΥ" έναντι "ΝΗΥ" -- πιθανό
    typo, όχι σίγουρο ταίριασμα) -- αυτά μένουν για το χειροκίνητο dedup sweep."""
    s = unicodedata.normalize('NFD', name or '')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.upper().translate(_GREEK_LATIN_HOMOGLYPHS)
    return re.sub(r'[^A-Z0-9Α-Ω]', '', s)


def _find_or_create_machine(conn, name):
    if not name:
        return None
    row = conn.execute('SELECT id FROM tbl_machines WHERE name=?', (name,)).fetchone()
    if row:
        return row['id']
    norm = _normalize_machine_code(name)
    if norm:
        for r in conn.execute('SELECT id, name FROM tbl_machines').fetchall():
            if _normalize_machine_code(r['name']) == norm:
                return r['id']
    cur = conn.execute('INSERT INTO tbl_machines (name) VALUES (?)', (name,))
    return cur.lastrowid


def get_machine_merge_candidates():
    """Υποψήφια μηχανήματα προς συγχώνευση -- ΜΟΝΟ exact-normalized-match (ίδιο
    equivalence class με _normalize_machine_code/_find_or_create_machine), σε
    αντίθεση με το supplier tool: το tbl_machines δεν έχει καμία δεύτερη
    ταυτοποίηση σαν το ΑΦΜ, άρα κανένα STRONG tier δεν είναι δυνατό. Η
    πραγματική αξία του dedup sweep 2026-09-06 ήταν κυρίως fuzzy/σημασιολογικό
    ταίριασμα (διάβασμα PDF) -- ρητά εκτός αυτοματισμού, ίδιο με το OCR-
    substitution tier του description/supplier tool. Αναμένονται λίγα ή
    καθόλου αποτελέσματα σε ήδη καθαρισμένα δεδομένα -- το χειροκίνητο merge-
    by-id παραμένει ο κύριος τρόπος χρήσης εδώ."""
    machines = list_machines()
    groups = {}
    for m in machines:
        norm = _normalize_machine_code(m['name'])
        if not norm:
            continue
        groups.setdefault(norm, []).append(m)

    dismissed = _load_dismissed_keys('machine')
    candidates = []
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda m: m['id'])
        keep, rest = group[0], group[1:]
        others = [
            {'id': o['id'], 'name': o['name'], 'dismiss_key': f"{keep['id']}:{o['id']}"}
            for o in rest if f"{keep['id']}:{o['id']}" not in dismissed
        ]
        if not others:
            continue
        candidates.append({
            'keep_id': keep['id'], 'keep_name': keep['name'],
            'others': others,
        })
    return candidates


# Μορφή ελληνικής πινακίδας: 3 γράμματα ΜΟΝΟ από τα 14 κοινά Ελληνικών/Λατινικών
# (Α Β Ε Ζ Η Ι Κ Μ Ν Ο Ρ Τ Υ Χ — το _normalize_machine_code τα φέρνει ήδη σε λατινικά) + 4
# ψηφία: NHY7148, «ΚΙΗ 2990», «ΝΧΥ-1513» — όχι «CAT 980» (C, 3 ψηφία) ή «NLY 7146» (L δεν
# υπάρχει σε ελληνική πινακίδα). Κανόνας από τον χρήστη 2026-09-23. Ίδιος με το PLATE_RE
# του intake-tool's js/import.js. Οι πινακίδες μηχανημάτων έργων («ΜΕ» + 5 ψηφία) ΣΚΟΠΙΜΑ
# δεν ταιριάζουν: είναι ακριβώς τα δικά μας μηχανήματα-στόχοι, όχι φορτηγά παράδοσης. Αφορά το «μεταφορικό μέσο» λάθος: το Gemini βάζει μερικές φορές ως
# μηχάνημα την πινακίδα του φορτηγού ΠΑΡΑΔΟΣΗΣ του προμηθευτή (πεδία «ΑΡ. ΟΧΗΜΑΤΟΣ»/
# «ΜΕΤΑΦΟΡΙΚΟ ΜΕΣΟ»), όχι το μηχάνημα-στόχο (βλ. ΝΧΥ1513/NLY 7146, sweep 2026-09-17).
_PLATE_RE = re.compile(r'^[ABEZHIKMNOPTYX]{3}\d{4}$')


def _is_plate_code(name):
    return bool(_PLATE_RE.match(_normalize_machine_code(name)))


def get_single_supplier_plate_machines():
    """Μηχανήματα με μορφή πινακίδας που εμφανίζονται σε τιμολόγια ΕΝΟΣ μόνο
    προμηθευτή — το χαρακτηριστικό σημάδι του φορτηγού παράδοσης εκείνου του
    προμηθευτή. Τα πραγματικά οχήματα της εταιρείας (π.χ. NHY7148) εμφανίζονται σε
    πολλούς προμηθευτές. Όχι όσα έχουν «Παράβλεψη» (kind 'plate', key = machine id)."""
    dismissed = _load_dismissed_keys('plate')
    with get_db() as conn:
        machines = [dict(r) for r in conn.execute('SELECT id, name FROM tbl_machines').fetchall()]
        out = []
        for m in machines:
            if not _is_plate_code(m['name']) or str(m['id']) in dismissed:
                continue
            rows = conn.execute(
                '''SELECT i.id AS invoice_id, i.doc_date, i.supplier_id, s.name AS supplier_name,
                          ii.description
                   FROM tbl_invoice_items ii JOIN tbl_invoices i ON i.id = ii.invoice_id
                   LEFT JOIN tbl_suppliers s ON s.id = i.supplier_id
                   WHERE ii.machine_id=? ORDER BY i.doc_date''', (m['id'],)
            ).fetchall()
            if not rows or len({r['supplier_id'] for r in rows}) != 1:
                continue
            descriptions = list(dict.fromkeys(r['description'] for r in rows if r['description']))
            out.append({
                'id': m['id'], 'name': m['name'], 'supplier_name': rows[0]['supplier_name'],
                'line_count': len(rows), 'invoice_count': len({r['invoice_id'] for r in rows}),
                'date_from': rows[0]['doc_date'], 'date_to': rows[-1]['doc_date'],
                'sample_descriptions': descriptions[:5], 'dismiss_key': str(m['id']),
            })
    return out


def get_machine_merge_preview(keep_id, merge_id):
    with get_db() as conn:
        items = conn.execute(
            'SELECT ii.description, ii.category, i.doc_date, i.doc_number '
            'FROM tbl_invoice_items ii JOIN tbl_invoices i ON i.id = ii.invoice_id '
            'WHERE ii.machine_id=? ORDER BY i.doc_date', (merge_id,)
        ).fetchall()
        alloc_count = conn.execute(
            'SELECT COUNT(*) as c FROM tbl_allocations WHERE machine_id=?', (merge_id,)
        ).fetchone()['c']
    return {
        'item_count': len(items), 'allocation_count': alloc_count,
        'items': [dict(r) for r in items[:50]],
    }


def merge_machines(keep_id, merge_id):
    if keep_id == merge_id:
        raise ValueError('Δεν μπορεί να συγχωνευτεί μηχάνημα με τον εαυτό του')
    with get_db() as conn:
        # Δύο FK, όχι ένα -- tbl_allocations (bulk-pool διαμοιρασμός 2ου σταδίου)
        # αναφέρεται σε machine_id ξεχωριστά από τα tbl_invoice_items.
        cur1 = conn.execute('UPDATE tbl_invoice_items SET machine_id=? WHERE machine_id=?', (keep_id, merge_id))
        cur2 = conn.execute('UPDATE tbl_allocations SET machine_id=? WHERE machine_id=?', (keep_id, merge_id))
        conn.execute('DELETE FROM tbl_machines WHERE id=?', (merge_id,))
    return {'reassigned_items': cur1.rowcount, 'reassigned_allocations': cur2.rowcount}


# Ορφανό = καμία αναφορά από ΚΑΝΕΝΑ από τα δύο FK (ίδια δύο με το merge_machines
# παραπάνω). Το merge_machines ήδη διαγράφει το δικό του merge_id -- αυτό καλύπτει
# όλους τους ΑΛΛΟΥΣ δρόμους που αφήνουν μηχάνημα με 0 χρήσεις (χειροκίνητη διόρθωση
# machine_id, διαγραφή τιμολογίου/γραμμής, split-tool).
_ORPHAN_MACHINE_WHERE = (
    'NOT EXISTS (SELECT 1 FROM tbl_invoice_items ii WHERE ii.machine_id = m.id) '
    'AND NOT EXISTS (SELECT 1 FROM tbl_allocations a WHERE a.machine_id = m.id)'
)


def get_orphan_machines():
    with get_db() as conn:
        rows = conn.execute(
            f'SELECT m.id, m.name, m.notes FROM tbl_machines m WHERE {_ORPHAN_MACHINE_WHERE} ORDER BY m.name'
        ).fetchall()
    return [dict(r) for r in rows]


def delete_orphan_machines(ids):
    """Διαγράφει ΜΟΝΟ όσα από τα ids είναι ακόμα ορφανά τη στιγμή της διαγραφής --
    ο έλεγχος ξαναγίνεται μέσα στο ίδιο DELETE, ώστε ένα μηχάνημα που απέκτησε
    γραμμή μετά τη φόρτωση της λίστας (π.χ. από άλλο παράθυρο) να μη χαθεί."""
    ids = [int(i) for i in ids]
    if not ids:
        return {'deleted': 0, 'skipped': 0}
    placeholders = ','.join('?' * len(ids))
    with get_db() as conn:
        cur = conn.execute(
            f'DELETE FROM tbl_machines WHERE id IN ({placeholders}) AND id IN '
            f'(SELECT m.id FROM tbl_machines m WHERE {_ORPHAN_MACHINE_WHERE})',
            ids
        )
    return {'deleted': cur.rowcount, 'skipped': len(ids) - cur.rowcount}


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


def _canonicalize_description(conn, category, description):
    """Ίδια λογική με το _find_or_create_machine (βλ. εκεί) αλλά χωρίς ξεχωριστό
    πίνακα-λεξικό: αντί για "βρες ή φτιάξε" εδώ είναι μόνο "βρες" -- αν ήδη
    υπάρχει γραμμή στην ΙΔΙΑ κατηγορία με description που κανονικοποιείται στο
    ίδιο κλειδί (κενά/παύλες/Ελληνικά-Λατινικά αγνοούνται), επιστρέφει το ήδη
    καταχωρημένο ΑΚΡΙΒΕΣ κείμενο αντί για το νεοεισερχόμενο -- ώστε δύο
    μορφοποιητικά διαφορετικές γραφές του ίδιου προϊόντος να μην ξαναδιχάσουν
    το ίδιο πρόβλημα που είχαμε στα μηχανήματα (βλ. λιπαντικά dedup sweep,
    2026-09-09: "AGRON UTTO SAE 80W 1X18L" έναντι OCR-αλλοιωμένων "AGRON UTTO
    BRE 80W 1X18"/"AGRON SUTTO SAB HOW AXIBL"). Αν δεν βρεθεί τίποτα, μένει
    ΑΝΕΓΓΙΧΤΟ όπως ήρθε -- δεν εφευρίσκουμε νέα μορφή, μόνο ταιριάζουμε με ό,τι
    ήδη υπάρχει (ίδιο conservative tier-1 σκεπτικό)."""
    if not description or not category:
        return description
    exact = conn.execute(
        'SELECT 1 FROM tbl_invoice_items WHERE category=? AND description=? LIMIT 1',
        (category, description)
    ).fetchone()
    if exact:
        return description
    norm = _normalize_machine_code(description)
    if not norm:
        return description
    for r in conn.execute('SELECT DISTINCT description FROM tbl_invoice_items WHERE category=?', (category,)).fetchall():
        if _normalize_machine_code(r['description']) == norm:
            return r['description']
    return description


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
        if r.get('description') and r.get('category'):
            r['description'] = _canonicalize_description(conn, r['category'], r['description'])
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
    """Καλεί ΚΑΙ το attach_pdf αυτόματα αν το staged JSON έχει source_pdf_path — δεν
    βασιζόμαστε πια αποκλειστικά στο front-end (js/import.js) για αυτό, γιατί οτιδήποτε
    κάνει confirm απευθείας μέσω αυτής της συνάρτησης (π.χ. ένα batch-import script πάνω
    στο bridge, χωρίς να περνάει από το Electron UI) παρέκαμπτε σιωπηλά το attach —
    επαναλαμβανόμενο πρόβλημα, βλ. intake-tool's audit-checkpoint memory. Το attach
    τρέχει ΜΕΤΑ το commit (εκτός του with-block) ώστε μια αποτυχία επισύναψης PDF να μην
    κάνει rollback ένα ήδη επιτυχές confirm — το χειροκίνητο "Επισύναψη" στο UI μένει ως
    fallback αν αποτύχει."""
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

    source_pdf_path = data.get('source_pdf_path')
    if source_pdf_path:
        # source_pdf_path: string (1 σελίδα, ιστορικό σχήμα) ή λίστα από strings σε
        # σειρά σελίδων (πολλές φωτογραφίες/σαρώσεις του ίδιου παραστατικού
        # συνδυάστηκαν σε ένα AI call, βλ. TODO.md) -- και στις δύο περιπτώσεις πρέπει
        # να καταλήξει ΕΝΑ attached PDF στο pdf_store.
        paths = source_pdf_path if isinstance(source_pdf_path, list) else [source_pdf_path]
        paths = [p for p in paths if p and os.path.exists(p)]
        try:
            if len(paths) == 1:
                attach_pdf(invoice_id, paths[0])
            elif len(paths) > 1:
                # Ίδια μηχανή με το "Εργαλείο ένωσης πολυσέλιδων παραστατικών" -- συγχωνεύει
                # τα N PDF σε ένα πολυσέλιδο πριν το attach, καμία ξεχωριστή λογική εδώ.
                _merge_pdfs_and_attach(invoice_id, paths)
        except Exception as e:
            print(f'confirm_staging_row: αποτυχία αυτόματης επισύναψης PDF για invoice '
                  f'{invoice_id} ({paths}): {e}', file=sys.stderr)

    return invoice_id


def reject_staging_row(staging_id):
    with get_db() as conn:
        row = conn.execute('SELECT status FROM tbl_import_staging WHERE id=?', (staging_id,)).fetchone()
        if not row:
            raise ValueError('Η εγγραφή εισαγωγής δεν βρέθηκε')
        if row['status'] != 'pending':
            raise ValueError('Η εγγραφή έχει ήδη επεξεργαστεί')
        conn.execute("UPDATE tbl_import_staging SET status='rejected' WHERE id=?", (staging_id,))


def update_invoice_from_data(invoice_id, data):
    """Ίδιο raw σχήμα με ένα staging row (ονόματα προμηθευτή/μηχανήματος, όχι
    ids) — το UI της διόρθωσης δεν χρειάζεται δική του λογική resolution.
    data['items'] μπορεί να περιέχει είτε ΜΙΑ γραμμή (παλιό μοτίβο: μόνο αυτή
    που επεξεργάζεται ο χειριστής, με 'id' αν είναι ήδη υπάρχουσα — τυχόν
    άλλες γραμμές του ίδιου τιμολογίου διαβάζονται από τη βάση και μένουν
    αμετάβλητες, ίδιο id, βλ. update_invoice — δεν κόβεται το FK τυχόν bulk
    pool τους) είτε ΟΛΕΣ τις γραμμές μαζί (νέο invoice-editor UI). Γραμμές
    ΧΩΡΙΣ 'id' εισάγονται πάντα ως καινούριες — βλ. bug 2026-08-26: πριν
    αυτή τη διόρθωση, μια γραμμή χωρίς 'id' έχανε αθόρυβα κάθε ίχνος της
    (ποτέ δεν έφτανε στο update_invoice), αφού μόνο απευθείας edited_by_id
    (κλειδωμένο σε υπάρχον id) περνούσε στο merged_items — ήταν λανθάνον
    γιατί το παλιό μονο-γραμμής modal πάντα έστελνε 'id'."""
    with get_db() as conn:
        existing_items = [dict(r) for r in conn.execute(
            'SELECT * FROM tbl_invoice_items WHERE invoice_id=? ORDER BY id', (invoice_id,)
        ).fetchall()]
        submitted_items = data.get('items') or []
        new_items = [it for it in submitted_items if not it.get('id')]
        edited_by_id = {it.get('id'): it for it in submitted_items if it.get('id')}
        merged_items = [edited_by_id.pop(ex['id'], ex) for ex in existing_items]
        for it in edited_by_id.values():
            it = dict(it)
            it.pop('id', None)  # δεν ταίριαξε σε υπάρχουσα γραμμή -> νέα εγγραφή
            merged_items.append(it)
        for it in new_items:
            merged_items.append(dict(it))

        header = _resolve_header(conn, data)
        resolved_items = _resolve_items(conn, merged_items)

    update_invoice(invoice_id, header, resolved_items)
    return invoice_id


# ── ΕΝΩΣΗ ΠΟΛΥΣΕΛΙΔΩΝ ΠΑΡΑΣΤΑΤΙΚΩΝ ────────────────────────────────────────────
# Ένα φυσικό πολυσέλιδο έγγραφο μπορεί να καταλήξει σε πάνω από μία staging
# γραμμή (κάθε σελίδα φωτογραφήθηκε/υποβλήθηκε ξεχωριστά) ή σε ένα ήδη
# confirmed τιμολόγιο (μία σελίδα) + μία ή περισσότερες staging γραμμές (οι
# υπόλοιπες σελίδες) — βλ. intake-tool's DONE.md, 2026-09-07 (DIDIS 284,
# ΚΑΥΚΑΣ 0050928). Οι δύο πραγματικές περιπτώσεις διέφεραν στο αν οι πηγές
# είχαν συμπληρωματικά (disjoint) ή επικαλυπτόμενα items — το UI αφήνει τον
# χειριστή να διαλέξει με checkbox το τελικό σύνολο γραμμών, οπότε εδώ είναι
# πάντα "πλήρης αντικατάσταση" (μέσω update_invoice με items χωρίς 'id'), ποτέ
# append· έτσι δεν χρειάζεται να ξεχωρίζουμε τις δύο περιπτώσεις στον κώδικα.

def find_duplicate_invoice(header):
    """Read-only έλεγχος αν υπάρχει ήδη confirmed τιμολόγιο με ίδιο
    (doc_number, doc_date, προμηθευτή) — ίδιο κριτήριο με το _find_duplicate
    που ήδη μπλοκάρει το confirm_staging_row, αλλά καλέσιμο ΠΡΙΝ την
    προσπάθεια confirm (το UI το καλεί when-clicked σε ΕΝΑ staging row, όχι
    eager για όλη τη λίστα — βλ. σχεδιασμό στο πλάνο). Δεν δημιουργεί ποτέ
    προμηθευτή αν δεν βρεθεί (σε αντίθεση με _find_or_create_supplier) — αν ο
    προμηθευτής δεν υπάρχει καν, σίγουρα δεν υπάρχει διπλότυπο."""
    doc_number = header.get('doc_number')
    doc_date = header.get('doc_date')
    if not doc_number or not doc_date:
        return None
    with get_db() as conn:
        supplier_id = None
        norm_vat = _normalize_vat(header.get('supplier_vat'))
        if norm_vat:
            for r in conn.execute('SELECT id, vat_number FROM tbl_suppliers WHERE vat_number IS NOT NULL'):
                if _normalize_vat(r['vat_number']) == norm_vat:
                    supplier_id = r['id']
                    break
        if supplier_id is None and header.get('supplier_name'):
            row = conn.execute(
                'SELECT id FROM tbl_suppliers WHERE name=?', (header['supplier_name'],)
            ).fetchone()
            if row:
                supplier_id = row['id']
        if supplier_id is None:
            return None
        row = conn.execute(
            '''SELECT i.id, i.doc_number, i.doc_date, i.total_amount, s.name as supplier_name
               FROM tbl_invoices i JOIN tbl_suppliers s ON s.id = i.supplier_id
               WHERE i.doc_number=? AND i.doc_date=? AND i.supplier_id=?''',
            (doc_number, doc_date, supplier_id)
        ).fetchone()
        return dict(row) if row else None


CURRENT_PDF_SENTINEL = '__CURRENT_PDF__'  # στη θέση ενός staging row's source_pdf_path μέσα σε
# pdf_paths_in_order -- σημαίνει "το ήδη-συνδεδεμένο PDF του target τιμολογίου εδώ στη σειρά".
# Resolved server-side (δεν εκθέτουμε ποτέ το πραγματικό PDF_STORE_DIR path στο frontend).


def _merge_pdfs_and_attach(invoice_id, pdf_paths_in_order, old_path=None):
    """Ενώνει τα PDF στη δοσμένη σειρά (λίστα paths -- πραγματικά staging
    source_pdf_path, ή/και το CURRENT_PDF_SENTINEL για το τρέχον PDF του
    invoice) σε ένα πολυσέλιδο αρχείο και το επισυνάπτει μέσω attach_pdf.
    old_path (το ΤΡΕΧΟΝ pdf_store αρχείο του invoice, PRIN από οποιαδήποτε
    header/items ενημέρωση) πρέπει να δοθεί από τον caller -- ΔΕΝ μπορεί να
    ξαναδιαβαστεί εδώ από τη βάση, γιατί το merge_documents καλεί πρώτα
    update_invoice, που ήδη μηδενίζει το source_pdf_filename στήλη (βλ.
    update_invoice_from_data's ίδιο-ακριβώς πρόβλημα, λυμένο εκεί με το
    attach_pdf να τρέχει ΜΕΤΑ). Το ΠΑΛΙΟ αρχείο στο pdf_store διαγράφεται
    πριν το attach_pdf ώστε να μην προσθέσει "(2)" στο όνομα. Τα πηγαία
    αρχεία (πλην του ήδη-διαγραμμένου old_path) διαγράφονται μετά την
    επιτυχή ένωση -- ίδιο pattern με το attach_pdf's "μετακίνηση, όχι
    αντιγραφή" σκεπτικό."""
    if not pdf_paths_in_order:
        return None
    from pypdf import PdfWriter
    old_path = os.path.abspath(old_path) if old_path else None

    resolved_paths = [old_path if p == CURRENT_PDF_SENTINEL else p for p in pdf_paths_in_order]
    if any(p is None for p in resolved_paths):
        raise ValueError('Δεν υπάρχει τρέχον συνδεδεμένο PDF για ένωση σε αυτό το τιμολόγιο')

    # Διαβάζει (writer.append) ΟΛΕΣ τις πηγές -- old_path included, αν είναι μία απ' αυτές --
    # πριν διαγραφεί οτιδήποτε, ώστε το merged αρχείο να μη χάσει σελίδες.
    pdf_paths_in_order = resolved_paths
    writer = PdfWriter()
    for p in pdf_paths_in_order:
        writer.append(p)
    os.makedirs(PDF_STORE_DIR, exist_ok=True)
    tmp_path = os.path.join(PDF_STORE_DIR, f'_merge_tmp_{invoice_id}.pdf')
    with open(tmp_path, 'wb') as f:
        writer.write(f)
    writer.close()

    # Τώρα ασφαλές να καθαρίσουμε τα πηγαία αρχεία -- old_path πάντα (ήδη
    # ενσωματωμένο στο merged αρχείο, αλλιώς θα μπλόκαρε το attach_pdf's
    # naming με "(2)"), και κάθε άλλη πηγή (staging pages) που δεν είναι το
    # ήδη-διαγραμμένο old_path.
    if old_path and os.path.exists(old_path):
        os.remove(old_path)
    for p in pdf_paths_in_order:
        ap = os.path.abspath(p)
        if ap != old_path and os.path.exists(p):
            os.remove(p)

    return attach_pdf(invoice_id, tmp_path)


def merge_documents(target_invoice_id, staging_ids, header, items, pdf_paths_in_order):
    """Ενώνει ένα ή περισσότερα staging rows (και προαιρετικά ένα ήδη
    confirmed τιμολόγιο) σε ΕΝΑ τιμολόγιο — header/items έρχονται ήδη
    οριστικοποιημένα από τον χειριστή (raw shape, ίδιο με ένα staging JSON).
    target_invoice_id=None -> δημιουργείται νέο τιμολόγιο (καθαρό staging+
    staging merge)· δοσμένο -> πλήρης αντικατάσταση των γραμμών του (βλ.
    update_invoice). Τα staging_ids που καταναλώθηκαν μαρκάρονται 'merged'
    (όχι 'rejected' — δεν απορρίφθηκαν ως άχρηστα, ενώθηκαν αλλού)."""
    with get_db() as conn:
        header_resolved = _resolve_header(conn, header)
        items_resolved = _resolve_items(conn, items)
        old_pdf_filename = None
        if target_invoice_id:
            row = conn.execute(
                'SELECT source_pdf_filename FROM tbl_invoices WHERE id=?', (target_invoice_id,)
            ).fetchone()
            old_pdf_filename = row['source_pdf_filename'] if row else None
    old_pdf_path = os.path.join(PDF_STORE_DIR, old_pdf_filename) if old_pdf_filename else None

    if target_invoice_id:
        update_invoice(target_invoice_id, header_resolved, items_resolved)
        invoice_id = target_invoice_id
    else:
        with get_db() as conn:
            invoice_id = _insert_invoice(conn, header_resolved, items_resolved)

    if pdf_paths_in_order:
        _merge_pdfs_and_attach(invoice_id, pdf_paths_in_order, old_path=old_pdf_path)

    with get_db() as conn:
        for sid in (staging_ids or []):
            conn.execute("UPDATE tbl_import_staging SET status='merged' WHERE id=?", (sid,))

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
        (invoice_item_id, item_data.get('category'), canonical_unit(item_data.get('unit')), total, total, now, now)
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


def delete_bulk_pool(pool_id):
    """Αναιρεί εντελώς τη σήμανση bulk μιας γραμμής — διαφορετικό από
    close_bulk_pool: εκεί (κλείσιμο) μένει ιστορικό "ήταν bulk, τελείωσε/
    ακυρώθηκε", εδώ διαγράφεται η ίδια η bulk-ότητα σαν να μην είχε ποτέ
    σημανθεί (π.χ. λάθος τσεκάρισμα bulk στο confirm μιας μεμονωμένης
    αγοράς). Επιτρέπεται μόνο αν δεν έχει γίνει ΚΑΜΙΑ κατανομή ποτέ —
    διαφορετικά υπάρχει πραγματικό ιστορικό κατανάλωσης που χάνεται σιωπηλά
    (ίδιος κίνδυνος με delete_invoice/delete_invoice_item)."""
    with get_db() as conn:
        pool = conn.execute('SELECT * FROM tbl_bulk_pools WHERE id=?', (pool_id,)).fetchone()
        if not pool:
            raise ValueError('Το απόθεμα δεν βρέθηκε')
        alloc_count = conn.execute(
            'SELECT COUNT(*) FROM tbl_allocations WHERE pool_id=?', (pool_id,)
        ).fetchone()[0]
        if alloc_count:
            raise ValueError(
                f'Δεν αναιρείται — υπάρχουν {alloc_count} καταχωρημένοι διαμοιρασμοί σε '
                f'μηχανήματα πάνω σε αυτό το απόθεμα. Αν πραγματικά χρειάζεται αναίρεση, '
                f'σβήσε πρώτα τους διαμοιρασμούς.'
            )
        conn.execute('DELETE FROM tbl_bulk_pools WHERE id=?', (pool_id,))


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

def add_invoice_review(invoice_id, note=None):
    """Χειροκίνητη επιθεώρηση: ο χρήστης είδε αυτό το flagged τιμολόγιο και το
    αφήνει όπως είναι εν γνώσει του — get_flagged_invoices() θα το δείχνει πλέον
    ως severity='reviewed' ανεξάρτητα τι λέει η αυτόματη ταξινόμηση, μέχρι να
    αναιρεθεί ρητά (remove_invoice_review). Ξεχωριστό από τους αυτόματους
    κανόνες, ώστε μια μελλοντική αλλαγή στο heuristic να μην ξαναχάνει την
    ανθρώπινη απόφαση."""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO tbl_invoice_reviews (invoice_id, note, reviewed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(invoice_id) DO UPDATE SET note=excluded.note, reviewed_at=excluded.reviewed_at
        ''', (invoice_id, note, _now()))
    return {'ok': True}


def remove_invoice_review(invoice_id):
    with get_db() as conn:
        conn.execute('DELETE FROM tbl_invoice_reviews WHERE invoice_id=?', (invoice_id,))
    return {'ok': True}


def get_flagged_invoices():
    """Τιμολόγια με πιθανά προβλήματα δεδομένων, ένα πέρασμα πάνω σε όλα τα
    τιμολόγια — μικρό dataset σε αυτή την κλίμακα, δεν χρειάζεται caching.
    Σειρά προτεραιότητας ανά τιμολόγιο: διπλότυπο > σοβαρό > μέτριο.
    - διπλότυπο: ίδιο (doc_number, doc_date, supplier_id) με άλλο τιμολόγιο
      (ίδια λογική με το _find_duplicate(), εδώ ως group query).
    - σοβαρό: υπάρχει γραμμή με "[ΑΓΝΩΣΤΟ" στην περιγραφή (το placeholder
      μοτίβο για δυσανάγνωστες σαρώσεις) ΚΑΙ με τιμή (value όχι None — αν
      είναι κενή δεν υπάρχει αριθμός να είναι λάθος, πέφτει στο no_value_at_all
      μέτριο παρακάτω αντί να θεωρείται αυτόματα σοβαρό μόνο κι μόνο επειδή η
      περιγραφή λέει "[ΑΓΝΩΣΤΟ"), ή SUM(items.value) αποκλίνει από
      το net_amount πέρα από ό,τι θα μπορούσε να εξηγηθεί ως ΕΞΟΔΑ/μεταφορικά
      (>20€ ή >5% του net_amount — το ΕΞΟΔΑ δεν είναι δικό του πεδίο στη
      βάση, μόνο στο τυπωμένο χαρτί, οπότε αυτό είναι ευριστικό όριο), ή
      net_amount+vat_amount αποκλίνει από το total_amount πέρα από το ίδιο
      όριο (ίδια λογική αναντιστοιχίας, άλλο ζευγάρι πεδίων — βλ. bug
      2026-08-27, τιμολόγια όπου το σύνολο στο χαρτί περιλάμβανε κάτι που
      δεν μπήκε ως ξεχωριστή γραμμή), ή γραμμή με vat_pct=24 σε τιμολόγιο
      πριν την 1/6/2016 (ο συντελεστής ΦΠΑ 24% δεν υπήρχε πριν αυτή την
      ημερομηνία στην Ελλάδα — σχεδόν σίγουρα λάθος ανάγνωση του 23%).
    - μέτριο: μικρότερη αναντιστοιχία εντός του παραπάνω ορίου (πιθανό
      ΕΞΟΔΑ, μη επιβεβαιωμένο) σε οποιοδήποτε από τα δύο ζεύγη πεδίων
      παραπάνω, ή γραμμή με ποσότητα αλλά χωρίς τιμή που δεν είναι γνωστή
      νόμιμη εξαίρεση (ΠΕΡΙΒ.ΕΙΣΦΟΡΑ, ή τιμολόγιο χωρίς net_amount συνολικά
      — price-less delivery note, αναμενόμενο), ή καμία γραμμή με value
      καθόλου (πιθανή σκόπιμη συνοπτική καταχώρηση παλιού migration αντί
      για πραγματικό λάθος — δεν αξίζει το "σοβαρό" μιας πραγματικής
      αριθμητικής αναντιστοιχίας).
    - reviewed: ό,τι κι αν θα έλεγε η αυτόματη ταξινόμηση παραπάνω, αν υπάρχει
      εγγραφή στο tbl_invoice_reviews (add_invoice_review) το τιμολόγιο
      εμφανίζεται πάντα ως "reviewed" — ρητή ανθρώπινη επιβεβαίωση ότι το
      είδε κάποιος και το αφήνει όπως είναι, δεν σιωπά τη σημαία, απλά
      αλλάζει κατηγορία σοβαρότητας."""
    with get_db() as conn:
        invoices = conn.execute('''
            SELECT i.id, i.doc_number, i.doc_date, i.net_amount, i.vat_amount,
                   i.total_amount, s.name as supplier_name
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
            'SELECT invoice_id, description, quantity, value, vat_pct FROM tbl_invoice_items'
        ).fetchall():
            items_by_invoice.setdefault(it['invoice_id'], []).append(it)

        reviews = {
            r['invoice_id']: r for r in
            conn.execute('SELECT invoice_id, note, reviewed_at FROM tbl_invoice_reviews').fetchall()
        }

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
            # Μόνο όταν η "[ΑΓΝΩΣΤΟ" γραμμή ΕΧΕΙ κάποια τιμή (πιθανώς αναξιόπιστη — δεν
            # ξέρουμε αν είναι σωστή) μετράει ως σοβαρό. Αν είναι εντελώς χωρίς τιμή, δεν
            # υπάρχει αριθμός να είναι λάθος — ίδια περίπτωση με το no_value_at_all
            # παρακάτω (π.χ. τιμολόγιο 33, ΜΑΚΡΟ), απλά τυχαίνει η περιγραφή να λέει
            # "[ΑΓΝΩΣΤΟ" αντί για κάτι άλλο — δεν αξίζει διαφορετική κατηγορία σοβαρότητας
            # μόνο γι' αυτό, βλ. bug 2026-08-29 (τιμολόγιο 49061 έδειχνε "σοβαρό" ενώ το
            # 33 με ταυτόσημη ουσιαστικά κατάσταση έδειχνε "μέτριο").
            has_unknown_line = any(
                it['description'] and '[ΑΓΝΩΣΤΟ' in it['description'] and it['value'] is not None
                for it in items
            )
            # Καμία γραμμή με value καθόλου (όχι απλά αναντιστοιχία, ΜΗΔΕΝΙΚΗ ανάλυση) —
            # συνήθως σκόπιμη συνοπτική καταχώρηση παλιού migration (π.χ. τιμολόγιο 33,
            # ΜΑΚΡΟ 0008-007020: 22 πραγματικές γραμμές συμπυκνωμένες σε μία περιγραφή
            # χωρίς ποσά, ενώ η κεφαλίδα είναι σωστή) — να ΜΗΝ βαρύνει σαν "σοβαρό" όπως
            # μια πραγματική αναντιστοιχία αριθμών, βλ. user 2026-08-25.
            no_value_at_all = bool(items) and all(it['value'] is None for it in items)
            diff = None
            if net_amount is not None:
                item_sum = sum(it['value'] for it in items if it['value'] is not None)
                diff = abs(item_sum - net_amount)

            # Ίδια λογική με diff (items vs net_amount) παραπάνω, άλλο ζεύγος πεδίων:
            # ό,τι δηλώνει το ίδιο το τιμολόγιο (net+ΦΠΑ) έναντι του καταχωρημένου
            # συνόλου του.
            total_diff = None
            if net_amount is not None and inv['vat_amount'] is not None and inv['total_amount'] is not None:
                total_diff = abs((net_amount + inv['vat_amount']) - inv['total_amount'])

            # 24% ΦΠΑ δεν υπήρχε στην Ελλάδα πριν την 1/6/2016 (ήταν 23%) — σχεδόν
            # σίγουρα λάθος ανάγνωση, βλ. bug 2026-08-27.
            impossible_vat_rate = bool(
                inv['doc_date'] and inv['doc_date'] < '2016-06-01' and
                any(it['vat_pct'] == 24 for it in items)
            )

            if has_unknown_line:
                severity = 'severe'
                reason = 'Δυσανάγνωστη/άγνωστη γραμμή'
            elif impossible_vat_rate:
                severity = 'severe'
                reason = 'Γραμμή με ΦΠΑ 24% σε τιμολόγιο πριν την 1/6/2016 (δεν υπήρχε αυτός ο συντελεστής τότε — πιθανό λάθος ανάγνωσης του 23%)'
            elif no_value_at_all and net_amount:
                severity = 'moderate'
                reason = 'Χωρίς αναλυτικές γραμμές αξίας (πιθανή σκόπιμη συνοπτική καταχώρηση, όχι απαραίτητα λάθος)'
            elif diff is not None and diff > max(20.0, 0.05 * net_amount):
                severity = 'severe'
                reason = f'Αναντιστοιχία {diff:.2f}€ (γραμμές έναντι net_amount)'
            elif total_diff is not None and total_diff > max(20.0, 0.05 * net_amount):
                severity = 'severe'
                reason = f'Αναντιστοιχία {total_diff:.2f}€ (net+ΦΠΑ έναντι καταχωρημένου συνόλου)'
            elif diff is not None and diff > 0.01:
                severity = 'moderate'
                reason = f'Μικρή αναντιστοιχία {diff:.2f}€ (πιθανό ΕΞΟΔΑ, μη επιβεβαιωμένο)'
            elif total_diff is not None and total_diff > 0.01:
                severity = 'moderate'
                reason = f'Μικρή αναντιστοιχία {total_diff:.2f}€ (net+ΦΠΑ έναντι συνόλου, μη επιβεβαιωμένο)'
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
            review = reviews.get(inv_id)
            if review:
                reason = f'Επιθεωρήθηκε — {reason}' + (f' ({review["note"]})' if review['note'] else '')
                severity = 'reviewed'
            flagged.append({
                'invoice_id': inv_id,
                'doc_number': inv['doc_number'],
                'doc_date': inv['doc_date'],
                'supplier_name': inv['supplier_name'],
                'net_amount': net_amount,
                'severity': severity,
                'reason': reason,
                'reviewed_at': review['reviewed_at'] if review else None,
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
        'flagged_reviewed': sum(1 for f in flagged if f['severity'] == 'reviewed'),
    }
