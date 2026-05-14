<#
  build-exe.ps1 -- one command to (re)build dist\storageanalyzer.exe

  Steps:
    1. Compile the optional native C++ walker in place. If no compiler is
       available this is skipped with a warning -- the exe still works on the
       pure-Python walker, just slower.
    2. Run PyInstaller against storageanalyzer.spec to produce a one-file exe.

  Quick turnaround: PyInstaller caches its analysis in build\, so re-runs after
  the first are fast. Editable-installed Python sources are picked up with no
  reinstall; only native (walker.cpp) changes trigger a recompile.

  First-time setup (installs PyInstaller + pybind11 into your environment):
    pip install -e ".[build]"

  Usage:
    .\build-exe.ps1            # fast incremental build
    .\build-exe.ps1 -Clean     # full rebuild, ignores caches
#>
param([switch]$Clean)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[1/2] Building native C++ extension (optional)..." -ForegroundColor Cyan
pip install -e . --no-build-isolation --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "  editable install failed" -ForegroundColor Red; exit 1 }

Write-Host "[2/2] Running PyInstaller..." -ForegroundColor Cyan
$pyiArgs = @("storageanalyzer.spec", "--noconfirm")
if ($Clean) { $pyiArgs += "--clean" }
pyinstaller @pyiArgs
if ($LASTEXITCODE -ne 0) { Write-Host "  PyInstaller failed" -ForegroundColor Red; exit 1 }

$exe = Join-Path $PSScriptRoot "dist\storageanalyzer.exe"
if (Test-Path $exe) {
    $size = "{0:N1} MB" -f ((Get-Item $exe).Length / 1MB)
    Write-Host ""
    Write-Host "Built: $exe ($size)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Build finished but $exe was not found." -ForegroundColor Red
    exit 1
}
