# =============================================================================
# VOXIS V4.0.0 DENSE — Windows Binary Build Script
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Run this on a Windows x64 machine to produce trinity_v8_core.exe.
# Requires: Python 3.11, pip, CUDA toolkit (optional but recommended)
#
# Usage (from repo root):
#   .\build_scripts\build_windows_binary.ps1
#   .\build_scripts\build_windows_binary.ps1 -SkipPythonDeps
#   .\build_scripts\build_windows_binary.ps1 -CpuOnly
# =============================================================================
param(
    [switch]$SkipPythonDeps,
    [switch]$CpuOnly
)

$ErrorActionPreference = 'Stop'
$ROOT = Split-Path -Parent $PSScriptRoot

Write-Host ""
Write-Host "  VOXIS V4.0.0 DENSE — Windows Binary Build" -ForegroundColor Cyan
Write-Host "  Glass Stone LLC © 2026" -ForegroundColor Cyan
Write-Host ""

# ── Preflight ─────────────────────────────────────────────────────────────────
Write-Host "[1/4] Checking prerequisites..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install Python 3.11 from python.org"
}
$pyVer = python --version 2>&1
Write-Host "      Python: $pyVer" -ForegroundColor Green

# ── Python dependencies ───────────────────────────────────────────────────────
if (-not $SkipPythonDeps) {
    Write-Host "[2/4] Installing Python dependencies..." -ForegroundColor Yellow

    # Pin setuptools + numpy for PyInstaller compatibility
    python -m pip install --upgrade pip wheel
    python -m pip install "setuptools==69.5.1" "numpy<2.0"

    if ($CpuOnly) {
        Write-Host "      Installing CPU-only torch..." -ForegroundColor Gray
        python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    } else {
        Write-Host "      Installing CUDA torch (cu124)..." -ForegroundColor Gray
        python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
    }

    python -m pip install -r "$ROOT\trinity_engine\requirements.txt"
    python -m pip install pyinstaller
    Write-Host "      Dependencies installed." -ForegroundColor Green
} else {
    Write-Host "[2/4] Skipping Python deps (-SkipPythonDeps)." -ForegroundColor Gray
}

# ── Build frozen binary ───────────────────────────────────────────────────────
Write-Host "[3/4] Building Trinity V8.1 Engine (PyInstaller)..." -ForegroundColor Yellow
Set-Location $ROOT
pyinstaller --noconfirm --clean trinity_v8_core_win.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }
Write-Host "      Binary built." -ForegroundColor Green

# ── Stage output ──────────────────────────────────────────────────────────────
Write-Host "[4/4] Staging binary for Electron..." -ForegroundColor Yellow
$binDir = "$ROOT\app\resources\bin"
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
Copy-Item "$ROOT\dist\trinity_v8_core.exe" "$binDir\trinity_v8_core.exe" -Force
Write-Host "      Staged → $binDir\trinity_v8_core.exe" -ForegroundColor Green

Write-Host ""
Write-Host "  Build complete! Next steps:" -ForegroundColor Cyan
Write-Host "  1. Download FFmpeg Windows binaries to app\resources\bin\" -ForegroundColor White
Write-Host "     (ffmpeg.exe + ffprobe.exe from https://github.com/BtbN/FFmpeg-Builds)" -ForegroundColor Gray
Write-Host "  2. Run: cd app && npm run electron:build:win" -ForegroundColor White
Write-Host ""
