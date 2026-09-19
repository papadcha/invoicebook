<#
.SYNOPSIS
  Αντιγράφει (ΟΧΙ μετακίνηση) το invoicebook.db + pdf_store σε εξωτερικό δίσκο, ώστε
  ο δίσκος να γίνει η μοναδική "ζωντανή" βάση που χρησιμοποιεί το intake-tool σε άλλον
  υπολογιστή, ενώ το τοπικό αντίγραφο εδώ μένει ανέγγιχτο ως στιγμιότυπο ασφαλείας.

  Τρέξε το ΜΙΑ φορά, όταν ο εξωτερικός δίσκος είναι έτοιμος/συνδεδεμένος.

.PARAMETER DriveLetter
  Το γράμμα του εξωτερικού δίσκου (π.χ. "E"). Υποχρεωτικό.

.PARAMETER VolumeLabel
  Προαιρετικό όνομα τόμου να μπει στον δίσκο (βοηθάει το μελλοντικό launcher script
  στον 2ο/3ο υπολογιστή να τον εντοπίζει από όνομα, όχι από γράμμα δίσκου — τα γράμματα
  δεν είναι σταθερά ανάμεσα σε υπολογιστές). Default: INVOICEBOOK-DATA.

.EXAMPLE
  .\transfer-to-external-drive.ps1 -DriveLetter E
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$DriveLetter,

    [string]$VolumeLabel = "INVOICEBOOK-DATA"
)

$ErrorActionPreference = "Stop"

$SourceDb      = "C:\invoices\backend\invoicebook.db"
$SourcePdfDir  = "C:\invoices\backend\pdf_store"
$DriveRoot     = "$($DriveLetter):\"
$DestRoot      = "$($DriveLetter):\InvoiceBookData"
$DestDb        = Join-Path $DestRoot "invoicebook.db"
$DestPdfDir    = Join-Path $DestRoot "pdf_store"

Write-Host "=== Έλεγχοι πριν την αντιγραφή ===" -ForegroundColor Cyan

# 1) Ο δίσκος υπάρχει;
if (-not (Test-Path $DriveRoot)) {
    Write-Error "Δεν βρέθηκε δίσκος στο $DriveRoot. Έλεγξε ότι είναι συνδεδεμένος και το γράμμα είναι σωστό."
}

# 2) Τα πηγαία αρχεία υπάρχουν;
if (-not (Test-Path $SourceDb))     { Write-Error "Δεν βρέθηκε $SourceDb" }
if (-not (Test-Path $SourcePdfDir)) { Write-Error "Δεν βρέθηκε $SourcePdfDir" }

# 3) Η βάση δεν είναι αυτή τη στιγμή ανοιχτή από άλλη διεργασία (π.χ. τρέχον invoicebook/
#    intake-tool) -- προσπάθεια exclusive άνοιγμα· αν αποτύχει, σταματάμε, γιατί αντιγραφή
#    ενώ γράφεται θα μπορούσε να πιάσει το αρχείο σε ασυνεπή κατάσταση.
try {
    $stream = [System.IO.File]::Open($SourceDb, 'Open', 'ReadWrite', 'None')
    $stream.Close()
} catch {
    Write-Error "Το $SourceDb φαίνεται να είναι ανοιχτό από άλλο πρόγραμμα. Έκλεισε ΠΡΩΤΑ το invoicebook/intake-tool και ξανατρέξε το script."
}

# 4) Αρκετός ελεύθερος χώρος στον δίσκο; (με 20% περιθώριο)
$needed = (Get-Item $SourceDb).Length + (Get-ChildItem $SourcePdfDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
$neededWithMargin = [math]::Ceiling($needed * 1.2)
$freeSpace = (Get-PSDrive $DriveLetter).Free
if ($freeSpace -lt $neededWithMargin) {
    $neededGb = [math]::Round($neededWithMargin / 1GB, 2)
    $freeGb = [math]::Round($freeSpace / 1GB, 2)
    Write-Error "Δεν επαρκεί ο χώρος στον δίσκο $($DriveLetter): χρειάζονται ~$neededGb GB, υπάρχουν $freeGb GB ελεύθερα."
}

Write-Host "Όλοι οι έλεγχοι πέρασαν." -ForegroundColor Green
Write-Host ""
Write-Host "=== Αντιγραφή (η πηγή ΔΕΝ αγγίζεται) ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $DestRoot | Out-Null

Write-Host "Αντιγραφή invoicebook.db..."
Copy-Item -Path $SourceDb -Destination $DestDb -Force

Write-Host "Αντιγραφή pdf_store (~2700+ αρχεία, μπορεί να πάρει λίγη ώρα)..."
robocopy $SourcePdfDir $DestPdfDir /E /R:2 /W:5 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error "Το robocopy ανέφερε σφάλμα (exit code $LASTEXITCODE). Έλεγξε τον δίσκο και ξανατρέξε."
}

Write-Host ""
Write-Host "=== Επαλήθευση ===" -ForegroundColor Cyan

$srcCount = (Get-ChildItem $SourcePdfDir -Recurse -File).Count
$dstCount = (Get-ChildItem $DestPdfDir -Recurse -File).Count
$srcDbSize = (Get-Item $SourceDb).Length
$dstDbSize = (Get-Item $DestDb).Length

Write-Host "PDF αρχεία -- πηγή: $srcCount, προορισμός: $dstCount"
Write-Host "Μέγεθος db -- πηγή: $srcDbSize bytes, προορισμός: $dstDbSize bytes"

if ($srcCount -ne $dstCount -or $srcDbSize -ne $dstDbSize) {
    Write-Error "Η επαλήθευση απέτυχε -- δεν ταιριάζουν αριθμοί/μεγέθη. ΜΗΝ χρησιμοποιήσεις ακόμα το αντίγραφο στον δίσκο."
}

Write-Host "Η επαλήθευση πέτυχε -- η αντιγραφή είναι πλήρης και σωστή." -ForegroundColor Green

# 5) Προαιρετικό όνομα τόμου, ώστε το launcher script στον άλλο υπολογιστή να βρίσκει
#    τον δίσκο από όνομα (σταθερό) αντί για γράμμα (μεταβλητό ανά υπολογιστή/σύνδεση).
try {
    $vol = Get-Volume -DriveLetter $DriveLetter
    if ($vol.FileSystemLabel -ne $VolumeLabel) {
        Set-Volume -DriveLetter $DriveLetter -NewFileSystemLabel $VolumeLabel
        Write-Host "Το όνομα τόμου ορίστηκε σε '$VolumeLabel'."
    }
} catch {
    Write-Warning "Δεν μπόρεσα να ορίσω όνομα τόμου αυτόματα -- όρισέ το χειροκίνητα (δεξί κλικ στον δίσκο > Μετονομασία) σε '$VolumeLabel' για να το βρίσκει εύκολα το launcher script."
}

Write-Host ""
Write-Host "=== Έτοιμο ===" -ForegroundColor Green
Write-Host "Δεδομένα στον δίσκο: $DestRoot"
Write-Host "Το τοπικό αντίγραφο εδώ ($SourceDb) ΔΕΝ πειράχτηκε -- μένει ως στιγμιότυπο ασφαλείας."
Write-Host ""
Write-Host "Επόμενο βήμα: στον άλλο υπολογιστή, το intake-tool πρέπει να δείχνει σε:"
Write-Host "  INVOICES_DB_PATH = <γράμμα δίσκου εκεί>:\InvoiceBookData\invoicebook.db"
Write-Host "Πριν αποσυνδέσεις τον δίσκο: κλείσε πρώτα την εφαρμογή, μετά 'Ασφαλής κατάργηση'."
