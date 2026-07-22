# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

InvoiceBook (`invoicebook`) — a Greek-language Electron desktop app for a business to log and track supplier invoices (Καταχώρηση και παρακολούθηση τιμολογίων προμηθευτών). UI, code comments, and error messages are in Greek; keep new user-facing strings and comments in Greek to stay consistent.

## Commands

- Run the app: `npm start` (launches Electron; there is no separate dev/build step — files are loaded directly, no bundler).
- No test suite, linter, or build pipeline exists in this repo yet.
- The Python backend has no external dependencies (`requirements.txt` — stdlib only: `sqlite3`, `json`, `csv`). It is not run standalone; Electron's main process spawns it (see below).

## Architecture

**Two-process design.** `main.js` (Electron main process) spawns a long-lived Python subprocess (`backend/bridge.py`) and talks to it over stdio using newline-delimited JSON (`{id, cmd, payload}` requests → `{id, result}` / `{id, error, trace}` responses). The renderer never talks to Python directly — it calls `window.api.call(cmd, payload)` (exposed via `preload.js` with `contextIsolation: true`, no `nodeIntegration`), which goes through `ipcMain.handle('python', ...)` in `main.js`.

**Command allowlist must stay in sync in two places.** `main.js` has `ALLOWED_PYTHON_COMMANDS` (a `Set`) and `backend/bridge.py`'s `handle()` has a matching chain of `if cmd == '...'`. Adding a new Python command requires updating *both* — the comment in `main.js` calls this out explicitly because otherwise the new command fails silently (rejected before it ever reaches Python).

**Backend layering:** `backend/bridge.py` is purely the stdio protocol handler (parses requests, dispatches to `database.py`, serializes responses). `backend/database.py` is the actual SQLite access layer — all business logic and queries live here, using a `get_db()` context manager that commits on success / rolls back on exception.

**Data directory depends on packaged state.** `main.js` sets `DATA_DIR` to `app.getPath('userData')` when `app.isPackaged`, otherwise to the `backend/` folder itself (so during `npm start` dev runs, `invoicebook.db` and `pdf_store/` stay alongside the code for easy inspection/reset). This is passed to the Python side via the `INVOICEBOOK_DATA_DIR` env var, which `bridge.py` uses to place `invoicebook.db` and `pdf_store/`.

**Schema migrations:** `database/schema.sql` is the full current schema, applied as-is to a fresh DB. `database/migration_NNN_*.sql` files are incremental upgrades for existing DBs, tracked via `tbl_schema_version` and driven by `CURRENT_SCHEMA_VERSION` / `migration_files` in `database.py`. Bumping the schema means: add a new `migration_NNN_*.sql`, register it in `migration_files`, and increment `CURRENT_SCHEMA_VERSION` — `schema.sql` should also be updated to reflect the fresh-install end state.

**PDF attachment is a move, not a copy.** `database.attach_pdf()` moves the source file into `backend/pdf_store/` renamed as `{invoice_id}_{original_name}`, deliberately so the app doesn't depend on the file staying at its original location.

**Import/staging flow:** CSV or JSON files are parsed (`bridge.py:_parse_import_file`) into staging rows written to `tbl_import_staging` (status `pending`). A human confirms or rejects each row individually (`confirm_staging_row` / `reject_staging_row`); confirming resolves/creates the supplier by VAT number or name (`_find_or_create_supplier`) and only then inserts real `tbl_invoices` / `tbl_invoice_items` rows. This staging table is designed to also accept a future OCR extraction path (`source='ocr_extract'`), not just CSV/JSON import.

**Frontend routing.** There's no framework/router — `js/main-app.js` has a small `Pages` map from page id to an HTML partial + JS module path. `navigateTo(pageId)` fetches the HTML fragment via `XMLHttpRequest`, injects it into `#page-container`, removes the previous page's `<script>` tag, and appends a fresh `<script type="module">` for the new page's JS (cache-busted with `?v=Date.now()`). Each page module in `src/pages/<name>/<name>.js` wires up its own DOM listeners on load and calls the backend via `window.pyCall` / `window.pyCallStrict` (thin wrappers around `window.api.call` defined globally in `main-app.js`). Shared helpers (HTML escaping, date/money formatting, button-lock spinner) live in `js/utils.js` and are imported by page modules.

**Suppliers are cached client-side.** `AppState.suppliers` loads once at startup (`get_suppliers`) and is reused for dropdowns across pages rather than refetched.
