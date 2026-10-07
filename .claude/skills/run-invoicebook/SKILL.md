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

Κλείσε το Electron, σβήσε `$env:TEMP\ib-test` και καθάρισε το env var (`Remove-Item Env:INVOICES_DB_PATH`). Το κλείσιμο μπορεί να τρέξει backup-on-close — με `INVOICES_DB_PATH` σε προσωρινό αντίγραφο έλεγξε ότι δεν ανεβαίνει backup του test db σε NAS/pCloud πριν το αφήσεις να τρέξει (δες `backend/backup.py` και τη ρύθμιση backup).

Σημ.: ο οδηγός αυτός γράφτηκε από τον κώδικα/τεκμηρίωση και δεν έχει ακόμα δοκιμαστεί end-to-end — διόρθωσέ τον στην πρώτη πραγματική χρήση.
