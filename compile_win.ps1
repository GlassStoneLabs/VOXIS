# ═══════════════════════════════════════════════════════════════════
#  VOXIS V4.0.0 DENSE — Windows Full Build Compiler
#  Copyright © 2026 Glass Stone LLC. All Rights Reserved.
#  CEO: Gabriel B. Rodriguez
# ═══════════════════════════════════════════════════════════════════
#
#  Builds the complete VOXIS Windows distribution:
#    1. Python engine → frozen executable via PyInstaller
#    2. Copies exe → app/resources/bin/
#    3. Tauri/Electron app → NSIS installer or portable exe
#
#  Usage:
#    .\compile_win.ps1                  # Full build (binary + app)
#    .\compile_win.ps1 -BinaryOnly      # Python binary only
#    .\compile_win.ps1 -AppOnly         # App only (binary must exist)
#    .\compile_win.ps1 -CpuOnly         # No CUDA (use CPU torch)
#    .\compile_win.ps1 -Clean           # Wipe dist/ first
# ═══════════════════════════════════════════════════════════════════
param(
    [switch]$BinaryOnly,
    [switch]$AppOnly,
    [switch]$CpuOnly,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$APP_DIR = Join-Path $ROOT "app"
$BIN_DEST = Join-Path $APP_DIR "resources\bin\trinity_v8_core.exe"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║  VOXIS V4.0.0 DENSE — Windows Build         ║" -ForegroundColor Cyan
Write-Host "  ║  Glass Stone LLC © 2026                      ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$buildStart = Get-Date

# ── Optional Clean ───────────────────────────────────────────────
if ($Clean) {
    Write-Host "  Cleaning previous build artifacts..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "$ROOT\dist", "$ROOT\build", "$APP_DIR\dist", "$APP_DIR\release" -ErrorAction SilentlyContinue
    Write-Host "  ✓ Clean complete" -ForegroundColor Green
}

# ═══════════════════════════════════════════════════════════════════
# PART 1: Python Binary
# ═══════════════════════════════════════════════════════════════════
if (-not $AppOnly) {
    Write-Host ""
    Write-Host "  STAGE 1 — Python Engine Compilation" -ForegroundColor Cyan

    # Check Python
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python not found. Install Python 3.11 from python.org"
    }
    $pyVer = (python --version 2>&1).ToString()
    Write-Host "  ✓ $pyVer" -ForegroundColor Green

    # Install dependencies
    Write-Host "  Installing build dependencies..." -ForegroundColor Yellow
    python -m pip install --upgrade pip wheel --quiet
    python -m pip install "setuptools==69.5.1" "numpy<2.0" --quiet

    if ($CpuOnly) {
        python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --quiet
    } else {
        python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124 --quiet
    }

    python -m pip install -r "$ROOT\requirements_win.txt" --quiet
    python -m pip install pyinstaller --quiet
    Write-Host "  ✓ Dependencies installed" -ForegroundColor Green

    # Build
    Write-Host "  Running PyInstaller (this takes 3-10 minutes)..." -ForegroundColor Yellow
    Set-Location $ROOT
    pyinstaller --noconfirm --clean trinity_v8_core_win.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    $binSrc = "$ROOT\dist\trinity_v8_core.exe"
    if (-not (Test-Path $binSrc)) { throw "Binary not found: $binSrc" }

    $binSize = (Get-Item $binSrc).Length / 1MB
    Write-Host "  ✓ Binary built: $($binSize.ToString('F0')) MB" -ForegroundColor Green

    # Stage to app/resources/bin/
    $binDir = Split-Path $BIN_DEST
    if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
    Copy-Item $binSrc $BIN_DEST -Force
    Write-Host "  ✓ Staged → $BIN_DEST" -ForegroundColor Green
}

# ═══════════════════════════════════════════════════════════════════
# PART 2: Frontend App
# ═══════════════════════════════════════════════════════════════════
if (-not $BinaryOnly) {
    Write-Host ""
    Write-Host "  STAGE 2 — Frontend App Build" -ForegroundColor Cyan

    if (-not (Test-Path $BIN_DEST)) {
        throw "Binary not found at $BIN_DEST — run without -AppOnly first"
    }

    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "Node.js/npm not found. Install from nodejs.org"
    }

    Set-Location $APP_DIR
    npm install --silent
    Write-Host "  ✓ npm dependencies installed" -ForegroundColor Green

    # Build Tauri app
    if (Test-Path "$APP_DIR\src-tauri") {
        Write-Host "  Building Tauri app..." -ForegroundColor Yellow
        npm run tauri build 2>&1
        Write-Host "  ✓ Tauri build complete" -ForegroundColor Green
    } else {
        Write-Host "  Building Electron app..." -ForegroundColor Yellow
        $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
        npm run electron:build:win 2>&1
        Write-Host "  ✓ Electron build complete" -ForegroundColor Green
    }
}

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
$elapsed = (Get-Date) - $buildStart
Write-Host ""
Write-Host "  Build Complete in $($elapsed.Minutes)m $($elapsed.Seconds)s" -ForegroundColor Cyan
if (Test-Path $BIN_DEST) {
    $sz = (Get-Item $BIN_DEST).Length / 1MB
    Write-Host "  ● Binary  $($sz.ToString('F0')) MB  $BIN_DEST" -ForegroundColor Green
}

# Check for installer output
$installer = Get-ChildItem "$APP_DIR\release\*" -Include "*.msi","*.exe","*.nsis" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($installer) {
    $isz = $installer.Length / 1MB
    Write-Host "  ● Installer  $($isz.ToString('F0')) MB  $($installer.FullName)" -ForegroundColor Green
}
Write-Host ""
