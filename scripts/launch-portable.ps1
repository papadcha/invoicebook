<#
.SYNOPSIS
  Ξεκινάει το invoicebook (ή το intake-tool, βλ. -App) δείχνοντας στα δεδομένα
  (invoicebook.db + pdf_store) πάνω στον φορητό δίσκο, όποιο γράμμα δίσκου κι αν πήρε σε
  αυτόν τον υπολογιστή — τον εντοπίζει από το ΟΝΟΜΑ ΤΟΜΟΥ (volume label), όχι από σταθερό
  γράμμα. Και τα δύο προγράμματα διαβάζουν το ίδιο INVOICES_DB_PATH. (Το report-tool
  αποσύρθηκε 2026-09-26 — 100% λειτουργική ενσωμάτωση στο invoicebook· δεν είναι πια
  επιλογή εδώ.)

  Μετακομισμένο εδώ από το C:\intake-tool 2026-09-30 (βλ. invoicebook's TODO.md, «Κλείσιμο
  κεφαλαίου intake-tool» — Β) — το invoicebook είναι πλέον ο «κύριος» κόμβος, οπότε αυτό
  το script (κοινό launcher και για τα δύο προγράμματα) ζει στο δικό του repo. Το
  C:\intake-tool\launch-portable.ps1 έμεινε ως thin redirect προς εδώ, ώστε η ήδη
  υπάρχουσα συνήθεια (`cd C:\intake-tool; .\launch-portable.ps1 ...`) να μη σπάσει —
  το intake-tool δεν έχει αποσυρθεί ακόμα.

.PARAMETER App
  Ποιο πρόγραμμα θα ανοίξει: invoicebook (default, εδώ είναι το repo του) ή intake-tool
  (αδερφός φάκελος ..\..\intake-tool).

.PARAMETER VolumeLabel
  Το όνομα τόμου του φορητού δίσκου. Default: INVOICEBOOK-DATA.

.PARAMETER InvoicebookRepoDir
  Πού βρίσκεται το invoicebook (`invoices`) repo σε ΑΥΤΟΝ τον υπολογιστή — χρειάζεται
  ΠΑΝΤΑ (και για τα δύο προγράμματα) γιατί το intake-tool κάνει dynamic import του
  backend/database.py από εδώ. Default: ο ίδιος ο φάκελος-γονέας αυτού του script
  (`scripts\..`), αφού πλέον ζει μέσα στο ίδιο το invoicebook repo.

.PARAMETER IntakeToolRepoDir
  Πού βρίσκεται το intake-tool repo σε αυτόν τον υπολογιστή — χρειάζεται μόνο για
  `-App intake-tool`. Default: αδερφός φάκελος "..\intake-tool" δίπλα στο invoicebook
  repo (ίδια σύμβαση με το dev setup).

.EXAMPLE
  .\launch-portable.ps1
.EXAMPLE
  .\launch-portable.ps1 -App intake-tool
.EXAMPLE
  .\launch-portable.ps1 -InvoicebookRepoDir "D:\Projects\invoices"
#>

param(
    [ValidateSet("invoicebook", "intake-tool")]
    [string]$App = "invoicebook",
    [string]$VolumeLabel = "INVOICEBOOK-DATA",
    [string]$InvoicebookRepoDir = (Join-Path $PSScriptRoot ".."),
    [string]$IntakeToolRepoDir = (Join-Path $PSScriptRoot "..\..\intake-tool")
)

$ErrorActionPreference = "Stop"

Write-Host "=== Έλεγχοι πριν την εκκίνηση ===" -ForegroundColor Cyan

# 1) Εντοπισμός του φορητού δίσκου από όνομα τόμου, όχι γράμμα.
$vol = Get-Volume | Where-Object { $_.FileSystemLabel -eq $VolumeLabel }
if (-not $vol) {
    Write-Error "Δεν βρέθηκε δίσκος με όνομα τόμου '$VolumeLabel'. Σύνδεσε τον φορητό δίσκο με τα δεδομένα και ξαναδοκίμασε."
}
if ($vol.Count -gt 1) {
    Write-Error "Βρέθηκαν πάνω από ένας δίσκοι με όνομα '$VolumeLabel' -- αφαίρεσε τον περιττό πριν συνεχίσεις."
}
$driveLetter = $vol.DriveLetter
$dbPath = "$($driveLetter):\InvoiceBookData\invoicebook.db"

if (-not (Test-Path $dbPath)) {
    Write-Error "Βρέθηκε ο δίσκος ($driveLetter):\, αλλά όχι $dbPath. Έλεγξε ότι η μεταφορά δεδομένων (transfer-to-external-drive.ps1) έχει ήδη γίνει σε αυτόν τον δίσκο."
}

# 2) Το invoicebook repo υπάρχει σε αυτόν τον υπολογιστή; (χρειάζεται πάντα, και για τα
#    δύο προγράμματα -- βλ. .PARAMETER InvoicebookRepoDir παραπάνω.)
$InvoicebookRepoDir = [System.IO.Path]::GetFullPath($InvoicebookRepoDir)
if (-not (Test-Path (Join-Path $InvoicebookRepoDir "backend\database.py"))) {
    Write-Error "Δεν βρέθηκε invoicebook repo στο '$InvoicebookRepoDir' (λείπει backend\database.py). Πέρασε το σωστό μονοπάτι με -InvoicebookRepoDir, ή αντίγραψε πρώτα το repo σε αυτόν τον υπολογιστή."
}

# 3) Φάκελος του προγράμματος που θα ανοίξει + node_modules εκεί (npm install μία φορά
#    ανά υπολογιστή, ανά repo).
$appDir = switch ($App) {
    "invoicebook" { $InvoicebookRepoDir }
    "intake-tool" { [System.IO.Path]::GetFullPath($IntakeToolRepoDir) }
}
if (-not (Test-Path (Join-Path $appDir "package.json"))) {
    Write-Error "Δεν βρέθηκε το $App στο '$appDir' (λείπει package.json) -- κάνε πρώτα git clone εκεί."
}
if (-not (Test-Path (Join-Path $appDir "node_modules"))) {
    Write-Error "Δεν βρέθηκε node_modules στο $appDir -- τρέξε πρώτα 'npm install' μέσα εκεί (μία φορά, σε αυτόν τον υπολογιστή)."
}

# 4) Python υπάρχει στο PATH;
$pythonOk = $null -ne (Get-Command python -ErrorAction SilentlyContinue)
if (-not $pythonOk) {
    Write-Error "Δεν βρέθηκε 'python' στο PATH αυτού του υπολογιστή -- εγκατέστησε Python (stdlib μόνο, καμία επιπλέον βιβλιοθήκη χρειάζεται)."
}

Write-Host "Δίσκος: $($driveLetter):\  (όνομα τόμου: $VolumeLabel)"
Write-Host "Βάση:   $dbPath"
Write-Host "Repo:   $InvoicebookRepoDir"
Write-Host "App:    $App ($appDir)"
Write-Host ""
Write-Host "=== Εκκίνηση $App ===" -ForegroundColor Cyan

$env:INVOICES_DB_PATH = $dbPath
$env:INVOICEBOOK_REPO_DIR = $InvoicebookRepoDir

Push-Location $appDir
try {
    npm start
} finally {
    Pop-Location
}
