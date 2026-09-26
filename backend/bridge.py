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
DB_PATH = os.environ.get('INVOICES_DB_PATH') or os.path.join(_data_dir, 'invoicebook.db')

import database
import expvault_export
import backup
database.DB_NAME = DB_PATH
database.PDF_STORE_DIR = os.path.join(os.path.dirname(DB_PATH), 'pdf_store')
database.initialize_database()
backup.DB_PATH = DB_PATH
backup.PDF_STORE_DIR = database.PDF_STORE_DIR
backup.DATA_DIR = os.path.dirname(DB_PATH)


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

    if cmd == 'get_orphan_suppliers':
        return database.get_orphan_suppliers()

    if cmd == 'get_suppliers_with_invalid_vat':
        return database.get_suppliers_with_invalid_vat()

    if cmd == 'delete_orphan_suppliers':
        return database.delete_orphan_suppliers(payload['ids'])

    # ── ΤΙΜΟΛΟΓΙΑ ─────────────────────────────────────────────────────────────
    if cmd == 'get_invoice':
        return database.get_invoice(_int_id(payload))

    if cmd == 'delete_invoice':
        return {'ok': True, **database.delete_invoice(_int_id(payload))}

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

    if cmd == 'parse_import_file':
        return _parse_import_file(payload['file_path'])

    if cmd == 'stage_rows':
        return database.import_staging_rows(
            payload['rows'], batch_label=payload.get('batch_label'), source='ocr_extract'
        )

    if cmd == 'find_duplicate_invoice':
        return database.find_duplicate_invoice(payload['header'])

    if cmd == 'merge_documents':
        return {'invoice_id': database.merge_documents(
            payload.get('target_invoice_id'),
            payload.get('staging_ids') or [],
            payload['header'],
            payload['items'],
            payload.get('pdf_paths_in_order') or [],
        )}

    if cmd == 'list_categories':
        return database.list_categories()

    if cmd == 'list_machines':
        return database.list_machines()

    # ── ΣΥΓΧΩΝΕΥΣΕΙΣ ─────────────────────────────────────────────────────────
    if cmd == 'get_supplier_merge_candidates':
        return database.get_supplier_merge_candidates()

    if cmd == 'get_supplier_merge_preview':
        return database.get_supplier_merge_preview(_int_id(payload, 'keep_id'), _int_id(payload, 'merge_id'))

    if cmd == 'merge_suppliers':
        return database.merge_suppliers(_int_id(payload, 'keep_id'), _int_id(payload, 'merge_id'))

    if cmd == 'get_description_merge_candidates':
        return database.get_description_merge_candidates()

    if cmd == 'merge_item_descriptions':
        return database.merge_item_descriptions(payload['category'], payload['keep'], payload['merge_list'])

    if cmd == 'get_machine_merge_candidates':
        return database.get_machine_merge_candidates()

    if cmd == 'get_machine_merge_preview':
        return database.get_machine_merge_preview(_int_id(payload, 'keep_id'), _int_id(payload, 'merge_id'))

    if cmd == 'merge_machines':
        return database.merge_machines(_int_id(payload, 'keep_id'), _int_id(payload, 'merge_id'))

    if cmd == 'get_orphan_machines':
        return database.get_orphan_machines()

    if cmd == 'delete_orphan_machines':
        return database.delete_orphan_machines(payload['ids'])

    if cmd == 'get_single_supplier_plate_machines':
        return database.get_single_supplier_plate_machines()

    if cmd == 'get_unit_variants':
        return database.get_unit_variants()

    if cmd == 'merge_units':
        return database.merge_units(payload['from_unit'], payload['to_unit'])

    if cmd == 'get_pdf_store_report':
        return database.get_pdf_store_report()

    if cmd == 'delete_orphan_pdfs':
        return database.delete_orphan_pdfs(payload['filenames'])

    if cmd == 'find_invoices_with_same_pdf':
        return database.find_invoices_with_same_pdf(payload.get('paths'))

    if cmd == 'dismiss_merge_candidate':
        database.dismiss_merge_candidate(payload['kind'], payload['candidate_key'])
        return {'ok': True}

    # ── ΠΕΡΙΗΓΗΣΗ ─────────────────────────────────────────────────────────────
    if cmd == 'list_invoice_items_by_category':
        return database.get_invoice_items_by_category(
            payload.get('category'), payload.get('date_from'), payload.get('date_to')
        )

    if cmd == 'get_flagged_invoices':
        return database.get_flagged_invoices()

    if cmd == 'get_invoice_status_summary':
        return database.get_invoice_status_summary()

    if cmd == 'review_flagged_invoice':
        return database.add_invoice_review(_int_id(payload, 'invoice_id'), payload.get('note'))

    if cmd == 'unreview_flagged_invoice':
        return database.remove_invoice_review(_int_id(payload, 'invoice_id'))

    if cmd == 'add_invoice_from_data':
        return {'id': database.add_invoice_from_data(payload['data'])}

    if cmd == 'update_invoice_from_data':
        return {'id': database.update_invoice_from_data(_int_id(payload), payload['data'])}

    if cmd == 'delete_invoice_item':
        database.delete_invoice_item(_int_id(payload, 'item_id'))
        return {'ok': True}

    if cmd == 'split_invoice_item':
        return database.split_invoice_item(_int_id(payload, 'item_id'), payload['splits'])

    # ── ΕΚΡΗΚΤΙΚΑ → expvault ─────────────────────────────────────────────────
    if cmd == 'expvault_export_preview':
        return expvault_export.preview(database, payload.get('date_from'), payload.get('date_to'))

    if cmd == 'expvault_export_write':
        return expvault_export.export_to_file(
            database, payload['path'], payload.get('date_from'), payload.get('date_to'),
            payload.get('tipos_overrides'), payload.get('exclude_ids'),
        )

    # ── ΑΝΤΙΓΡΑΦΑ ΑΣΦΑΛΕΙΑΣ (backup-on-close μόνο· καμία σελίδα ρυθμίσεων ακόμα —
    # η διαμόρφωση προορισμών γίνεται από το intake-tool's Ρυθμίσεις, ίδιο αρχείο) ──
    if cmd == 'get_backup_config':
        return backup.get_config()

    if cmd == 'run_backup':
        return backup.run_all_backups(payload.get('reason'))

    if cmd == 'save_backup_config':
        return backup.save_config(payload.get('paths') or [], payload.get('max_keep', 20))

    if cmd == 'set_backup_enabled':
        return backup.set_enabled(payload.get('enabled'))

    if cmd == 'list_backups':
        return backup.list_backups(payload['folder'])

    if cmd == 'restore_backup':
        return backup.restore_backup(payload['path'])

    if cmd == 'list_pdf_archives':
        return backup.list_pdf_archives(payload['folder'])

    if cmd == 'run_pdf_archive_now':
        return backup.run_pdf_archive_now()

    if cmd == 'restore_pdf_store':
        return backup.restore_pdf_store(payload['path'])

    if cmd == 'list_rclone_remotes':
        return backup.list_rclone_remotes()

    if cmd == 'list_remotes_detail':
        return backup.list_remotes_detail()

    if cmd == 'delete_remote':
        return backup.delete_remote(payload['name'])

    if cmd == 'list_manual_snapshots':
        return backup.list_manual_snapshots()

    if cmd == 'prune_manual_snapshots':
        return backup.prune_manual_snapshots()

    # ── ΑΠΟΘΕΜΑΤΑ ΠΡΟΣ ΔΙΑΜΟΙΡΑΣΜΟ ────────────────────────────────────────────
    if cmd == 'list_open_bulk_pools':
        return database.list_open_bulk_pools()

    if cmd == 'add_allocation':
        return database.add_allocation(
            _int_id(payload, 'pool_id'), payload.get('machine_name'), payload['quantity'],
            payload['allocation_date'], payload.get('notes')
        )

    if cmd == 'close_bulk_pool':
        database.close_bulk_pool(_int_id(payload, 'pool_id'), payload.get('note'))
        return {'ok': True}

    if cmd == 'delete_bulk_pool':
        database.delete_bulk_pool(_int_id(payload, 'pool_id'))
        return {'ok': True}

    if cmd == 'update_allocation':
        return database.update_allocation(
            _int_id(payload, 'allocation_id'), payload.get('machine_name'), payload['quantity'],
            payload['allocation_date'], payload.get('notes')
        )

    if cmd == 'delete_allocation':
        return database.delete_allocation(_int_id(payload, 'allocation_id'))

    if cmd == 'merge_bulk_pools':
        return database.merge_bulk_pools(_int_id(payload, 'keep_id'), _int_id(payload, 'merge_id'))

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
