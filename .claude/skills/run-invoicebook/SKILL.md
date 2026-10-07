---
name: run-invoicebook
description: Εκκίνηση και οδήγηση του InvoiceBook (Electron + Python backend) για να δεις μια αλλαγή να δουλεύει στην πραγματική εφαρμογή — με ασφαλή αντίγραφο της βάσης, όχι την πραγματική. Χρησιμοποίησέ το όταν ζητηθεί run/screenshot/δοκιμή UI.
---

# Εκκίνηση InvoiceBook για δοκιμή

Δεν υπάρχει build step ούτε test suite: τα αρχεία φορτώνονται απευθείας. Το Electron (main.js) σηκώνει το `backend/bridge.py` ως υποδιεργασία, άρα χρειάζεται `python` στο PATH με τα πακέτα του `requirements.txt`.

## 1. Ποτέ δοκιμή πάνω στην πραγματική βάση

Στο dev run η βάση είναι `backend/invoicebook.db` (+ `backend/pdf_store/`). Μια δοκιμή που γράφει (confirm, edit, merge, attach_pdf — το τελευταίο **μετακινεί** αρχεία) αλλοιώνει πραγματικά δεδομένα. Δούλεψε σε προσωρινό αντίγραφο:

```powershell
$t = "$env:TEMP\ib-test"; New-Item -ItemType Directory -Force $t | Out-Null
Copy-Item C:\invoices\backend\invoicebook.db $t\invoicebook.db
# pdf_store μόνο αν η δοκιμή αγγίζει PDF (είναι ~1,5 GB — αντίγραψε επιλεκτικά)
$env:INVOICES_DB_PATH = "$t\invoicebook.db"   # το pdf_store θα ψάχνεται δίπλα του
```

Αν η αλλαγή που δοκιμάζεις είναι μόνο ανάγνωση/UI, αρκεί αυτό. Αν πρέπει να γραφτεί στην πραγματική βάση, τρέξε πρώτα `python backend/snapshot_before_edit.py "περιγραφή"` (όχι `cp`).

Η εφαρμογή **αρνείται** να ξεκινήσει με βάση που λείπει (διάλογος σφάλματος) όταν έχει οριστεί `INVOICES_DB_PATH` ή δεν είναι packaged. Για σκόπιμα κενή βάση: `INVOICEBOOK_ALLOW_NEW_DB=1`.

## 2. Εκκίνηση

```powershell
cd C:\invoices
npm start            # κανονική εκκίνηση
```

Για οδήγηση από script (screenshots, κλικ) άνοιξε debug port και σύνδεσε Playwright μέσω CDP:

```powershell
npx electron . --remote-debugging-port=9222
```

Το Playwright **δεν** είναι dependency του repo — εγκατάστησέ το στο scratchpad, όχι στο repo:

```powershell
cd <scratchpad>; npm init -y; npm i playwright-core
```
```js
const { chromium } = require('playwright-core');
const b = await chromium.connectOverCDP('http://127.0.0.1:9222');
const page = b.contexts()[0].pages()[0];
await page.screenshot({ path: 'shot.png' });
```

Τα scripts γράφονται στο scratchpad, όχι στο repo.

## 3. Πλοήγηση / τι να ξέρεις

- Δεν υπάρχει router: το `js/main-app.js` έχει map `Pages`· η σελίδα φορτώνεται με `navigateTo(pageId)` και αντικαθιστά το `<script>` του module της. Στο script μπορείς να καλέσεις `page.evaluate(() => navigateTo('…'))` ή να πατήσεις το μενού.
- Κλήσεις backend από το renderer: `window.api.call(cmd, payload)` (ή `pyCall`/`pyCallStrict`). Νέα εντολή Python πρέπει να υπάρχει **και** στο `ALLOWED_PYTHON_COMMANDS` του `main.js` **και** στο `handle()` του `bridge.py`, αλλιώς αποτυγχάνει σιωπηλά.
- Αλλαγές σε `backend/*.py` χρειάζονται επανεκκίνηση του Electron (η Python διεργασία είναι μακρόβια)· αλλαγές σε `js/`, `src/` φορτώνονται με reload (Ctrl+R).
- Τα κείμενα UI είναι στα ελληνικά — ψάξε στοιχεία με ελληνικό κείμενο.

## 4. Καθαρισμός

Κλείσε το Electron (`Get-Process electron | Stop-Process -Force`) και σβήσε `$env:TEMP\ib-test`. Το env var δεν χρειάζεται καθάρισμα αν το όρισες μέσα στην εντολή εκκίνησης (κάθε κλήση PowerShell έχει δικό της περιβάλλον).

**Backup-on-close είναι ασφαλές με το προσωρινό αντίγραφο**: το `backup_config.json` αναζητείται δίπλα στη βάση (`backup.DATA_DIR = dirname(DB_PATH)`), άρα στο `ib-test` δεν υπάρχει και δεν ανεβαίνει τίποτα. **Μην αντιγράψεις** το `backup_config.json` εκεί.

## Δοκιμάστηκε (2026-10-07)

Τρέχει end-to-end: `npx electron . --remote-debugging-port=9222` (με `INVOICES_DB_PATH` στο αντίγραφο, ως background εντολή) → `[Bridge] Ready` → `connectOverCDP` → screenshot, `navigateTo('browse')`, κλήση backend. Παρατηρήσεις:
- Η εντολή εκκίνησης μένει σε εκτέλεση· τρέξ' την ως background και περίμενε ~6" πριν συνδεθείς. Το kill του Electron την τερματίζει με exit 255 (αναμενόμενο).
- `window.api.call(...)` επιστρέφει `{ok, result}`, όχι απευθείας το αποτέλεσμα.
- Η dev βάση `backend/invoicebook.db` είναι μικρή και **άδεια** (0 τιμολόγια, 0 προμηθευτές) — για δοκιμές με δεδομένα χρειάζεται αντίγραφο της πραγματικής βάσης (π.χ. από το data drive) και `snapshot`/προσοχή όπως παραπάνω.
- `page.evaluate(() => navigateTo('browse'))` δουλεύει· τα page ids είναι στο `Pages` του `js/main-app.js`.
