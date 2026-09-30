<#
.SYNOPSIS
  Πρώτη εγκατάσταση του invoicebook (+ intake-tool, αδερφός φάκελος) σε ΝΕΟ
  υπολογιστή. Τρέξε το ΜΙΑ φορά ανά υπολογιστή. Μετά, για καθημερινή χρήση,
  χρησιμοποίησε το launch-portable.ps1 (στο ίδιο scripts\ φάκελο).

  Χρειάζεται: internet σε αυτόν τον υπολογιστή (git clone + winget installs).
  Το ΜΟΝΟ αρχείο που χρειάζεται να μεταφέρεις εδώ χειροκίνητα (email/USB/δίσκος)
  είναι αυτό το ίδιο script -- όλα τα υπόλοιπα τα κατεβάζει μόνο του.

  Μετακομισμένο εδώ από το C:\intake-tool 2026-09-30 (βλ. invoicebook's TODO.md, «Κλείσιμο
  κεφαλαίου intake-tool» — Β) — το invoicebook είναι πλέον ο «κύριος» κόμβος (clone πρώτο,
  npm install και για τα δύο -- πριν έτρεχε npm install ΜΟΝΟ για το intake-tool, με το
  σκεπτικό ότι το invoicebook code χρειαζόταν μόνο σαν dynamic-import εξάρτηση χωρίς δικό
  του Electron run· αυτό δεν ισχύει πια, το invoicebook τρέχει κανονικά με δικό του
  `npm start`, βλ. CLAUDE.md).

.PARAMETER BaseDir
  Πού θα μπουν τα δύο repos, ως αδερφοί φάκελοι (BaseDir\invoices,
  BaseDir\intake-tool) -- ίδια σύμβαση με τον κύριο υπολογιστή. Default: C:\

.EXAMPLE
  .\setup-computer.ps1
#>

param(
    [string]$BaseDir = "C:\"
)

$ErrorActionPreference = "Stop"

function Ensure-Tool {
    param([string]$Command, [string]$WingetId, [string]$FriendlyName)
    if (Get-Command $Command -ErrorAction SilentlyContinue) {
        Write-Host "$FriendlyName -- ήδη εγκατεστημένο." -ForegroundColor Green
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Error "$FriendlyName δεν βρέθηκε, και δεν υπάρχει winget για αυτόματη εγκατάσταση. Εγκατέστησέ το χειροκίνητα και ξανατρέξε το script."
    }
    Write-Host "$FriendlyName δεν βρέθηκε -- εγκατάσταση μέσω winget..." -ForegroundColor Yellow
    winget install --id $WingetId -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Η εγκατάσταση του $FriendlyName απέτυχε (winget exit code $LASTEXITCODE). Εγκατέστησέ το χειροκίνητα και ξανατρέξε το script."
    }
    Write-Warning "$FriendlyName μόλις εγκαταστάθηκε -- ΚΛΕΙΣΕ και ξανάνοιξε αυτό το PowerShell παράθυρο πριν συνεχίσεις (για να ενημερωθεί το PATH), μετά ξανατρέξε το script."
    exit 0
}

Write-Host "=== Βήμα 1: Εργαλεία (git / Node.js / Python) ===" -ForegroundColor Cyan
Ensure-Tool -Command "git"    -WingetId "Git.Git"              -FriendlyName "Git"
Ensure-Tool -Command "node"   -WingetId "OpenJS.NodeJS.LTS"     -FriendlyName "Node.js"
Ensure-Tool -Command "python" -WingetId "Python.Python.3.12"    -FriendlyName "Python"

Write-Host ""
Write-Host "=== Βήμα 2: Κατέβασμα κώδικα (git clone) ===" -ForegroundColor Cyan

$InvoicesDir    = Join-Path $BaseDir "invoices"
$IntakeToolDir  = Join-Path $BaseDir "intake-tool"

if (Test-Path $InvoicesDir) {
    Write-Host "invoicebook repo ήδη υπάρχει στο $InvoicesDir -- ενημέρωση (git pull)..."
    git -C $InvoicesDir pull
} else {
    git clone https://github.com/papadcha/invoicebook.git $InvoicesDir
}

if (Test-Path $IntakeToolDir) {
    Write-Host "intake-tool repo ήδη υπάρχει στο $IntakeToolDir -- ενημέρωση (git pull)..."
    git -C $IntakeToolDir pull
} else {
    git clone https://github.com/papadcha/intake-tool.git $IntakeToolDir
}

Write-Host ""
Write-Host "=== Βήμα 3: npm install (και τα δύο προγράμματα τρέχουν δικό τους Electron) ===" -ForegroundColor Cyan
Push-Location $InvoicesDir
try {
    npm install
} finally {
    Pop-Location
}
Push-Location $IntakeToolDir
try {
    npm install
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "=== Έτοιμο ===" -ForegroundColor Green
Write-Host "invoicebook: $InvoicesDir"
Write-Host "intake-tool: $IntakeToolDir"
Write-Host ""
Write-Host "Επόμενο βήμα: σύνδεσε τον φορητό δίσκο με τα δεδομένα, μετά:"
Write-Host "  cd `"$InvoicesDir\scripts`""
Write-Host "  .\launch-portable.ps1"
