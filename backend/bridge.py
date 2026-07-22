# -*- coding: utf-8 -*-
"""
bridge.py — Python IPC bridge για το InvoiceBook.
Διαβάζει JSON commands από stdin, εκτελεί, γράφει JSON response στο stdout.
"""
import sys
import io
import json
import os
import csv
import traceback

# UTF-8 για stdin/stdout/stderr — κρίσιμο στα Windows, βλ. expvault/backend/bridge.py
if hasattr(sys.stdin, 'buffer'):
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                   errors='replace', line_buffering=True)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8',
                                   errors='replace', line_buffering=True)

_data_dir = os.environ.get(
    'INVOICEBOOK_DATA_DIR',
    os.path.dirname(os.path.abspath(__file__))
)
os.makedirs(_data_dir, exist_ok=True)
DB_PATH = os.path.join(_data_dir, 'invoicebook.db')

import database
database.DB_NAME = DB_PATH
database.PDF_STORE_DIR = os.path.join(_data_dir, 'pdf_store')
database.initialize_database()


def _int_id(payload, key='id'):
    try:
        val = int(payload.get(key))
    except (TypeError, ValueError):
        raise ValueError(f'Μη έγκυρο {key}: αναμένεται ακέραιος')
    if val <= 0:
        raise ValueError(f'Μη έγκυρο {key}: αναμένεται θετικός ακέραιος')
    return val


def _parse_import_file(file_path):
    """Επιστρέφει λίστα από dict (ένα ανά τιμολόγιο), με προαιρετικό 'items'."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.json':
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get('invoices', [])
        return data
    if ext == '.csv':
        rows = []
        with open(file_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({k: (v if v != '' else None) for k, v in r.items()})
        return rows
    raise ValueError(f'Μη υποστηριζόμενος τύπος αρχείου: {ext}')


def handle(cmd, payload):
    payload = payload or {}

    # ── ΠΡΟΜΗΘΕΥΤΕΣ ──────────────────────────────────────────────────────────
    if cmd == 'get_suppliers':
        return database.get_all_suppliers()

    if cmd == 'add_supplier':
        return {'id': database.add_supplier(payload['name'], payload.get('vat_number'), payload.get('notes'))}

    if cmd == 'update_supplier':
        database.update_supplier(_int_id(payload), payload['name'], payload.get('vat_number'), payload.get('notes'))
        return {'ok': True}

    if cmd == 'delete_supplier':
        database.delete_supplier(_int_id(payload))
        return {'ok': True}

    # ── ΤΙΜΟΛΟΓΙΑ ─────────────────────────────────────────────────────────────
    if cmd == 'get_invoices':
        return database.get_invoices(payload.get('date_from'), payload.get('date_to'), payload.get('supplier_id'))

    if cmd == 'get_invoice':
        return database.get_invoice(_int_id(payload))

    if cmd == 'add_invoice':
        return {'id': database.add_invoice(payload['header'], payload.get('items'))}

    if cmd == 'update_invoice':
        database.update_invoice(_int_id(payload), payload['header'], payload.get('items'))
        return {'ok': True}

    if cmd == 'delete_invoice':
        database.delete_invoice(_int_id(payload))
        return {'ok': True}

    if cmd == 'attach_pdf':
        stored_name = database.attach_pdf(_int_id(payload), payload['source_path'])
        return {'source_pdf_filename': stored_name}

    # ── ΕΙΣΑΓΩΓΗ ──────────────────────────────────────────────────────────────
    if cmd == 'import_staging_file':
        rows = _parse_import_file(payload['file_path'])
        database.import_staging_rows(rows, batch_label=payload.get('batch_label'), source='csv_import')
        return database.get_staging_batch(batch_label=payload.get('batch_label'), status='pending')

    if cmd == 'get_staging_batch':
        return database.get_staging_batch(payload.get('batch_label'), payload.get('status'))

    if cmd == 'confirm_staging_row':
        return {'invoice_id': database.confirm_staging_row(_int_id(payload))}

    if cmd == 'reject_staging_row':
        database.reject_staging_row(_int_id(payload))
        return {'ok': True}

    # ── ΑΝΑΦΟΡΕΣ ──────────────────────────────────────────────────────────────
    if cmd == 'get_summary':
        return database.get_summary(payload.get('year'), payload.get('month'))

    raise ValueError(f'Άγνωστη εντολή: {cmd}')


def main():
    print(json.dumps({'ready': True}))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = None
        try:
            msg = json.loads(line)
            result = handle(msg.get('cmd'), msg.get('payload'))
            print(json.dumps({'id': msg.get('id'), 'result': result}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({
                'id': msg.get('id') if msg else None,
                'error': str(e),
                'trace': traceback.format_exc(),
            }, ensure_ascii=False))


if __name__ == '__main__':
    main()
