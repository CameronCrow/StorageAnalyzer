<#
  build-installer.ps1 -- build dist\StorageAnalyzer-Setup-<version>.exe

  Steps:
    1. Build the standalone exe (delegates to build-exe.ps1).
    2. Compile installer\storageanalyzer.iss with Inno Setup's ISCC, stamping
       the version read from storageanalyzer.__version__.

  Inno Setup is required for step 2. If ISCC.exe is not found the script builds
  the exe and then exits with guidance instead of failing hard -- the one-file
  exe is already a complete, shippable artifact on its own.

  Install Inno Setup:  winget install JRSoftware.InnoSetup
                  or:  choco install innosetup

  Usage:
    .\build-installer.ps1            # build exe + installer
    .\build-installer.ps1 -Clean     # force a full exe rebuild first
#>
param([switch]$Clean)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- 1. build the exe ------------------------------------------------------
& "$PSScriptRoot\build-exe.ps1" @(if ($Clean) { "-Clean" })
if ($LASTEXITCODE -ne 0) { Write-Host "exe build failed" -ForegroundColor Red; exit 1 }

# --- version (single source of truth: __init__.py __version__) -------------
$initPy = Join-Path $PSScriptRoot "src\storageanalyzer\__init__.py"
$m = Select-String -Path $initPy -Pattern '__version__\s*=\s*["'']([^"'']+)["'']'
$version = $m.Matches[0].Groups[1].Value
if (-not $version) { Write-Host "could not read __version__" -ForegroundColor Red; exit 1 }

# --- 2. locate ISCC --------------------------------------------------------
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    Write-Host ""
    Write-Host "Inno Setup (ISCC.exe) not found -- skipping the installer." -ForegroundColor Yellow
    Write-Host "The standalone exe is ready at dist\storageanalyzer.exe." -ForegroundColor Yellow
    Write-Host "To build the installer, install Inno Setup and re-run:" -ForegroundColor Yellow
    Write-Host "    winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    exit 0
}

# --- 3. compile the installer ----------------------------------------------
Write-Host "Compiling installer (version $version) with $iscc ..." -ForegroundColor Cyan
& $iscc "/DMyAppVersion=$version" "$PSScriptRoot\installer\storageanalyzer.iss"
if ($LASTEXITCODE -ne 0) { Write-Host "ISCC failed" -ForegroundColor Red; exit 1 }

$setup = Join-Path $PSScriptRoot "dist\StorageAnalyzer-Setup-$version.exe"
if (Test-Path $setup) {
    $size = "{0:N1} MB" -f ((Get-Item $setup).Length / 1MB)
    Write-Host ""
    Write-Host "Built: $setup ($size)" -ForegroundColor Green
} else {
    Write-Host "ISCC reported success but $setup was not found." -ForegroundColor Red
    exit 1
}
