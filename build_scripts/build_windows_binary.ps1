# =============================================================================
# VOXIS V4.0.0 DENSE — Windows Binary Build Script (Tauri)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Run this on a Windows x64 machine to produce trinity_v8_core.exe.
# Requires: Python 3.11, pip, Rust/Cargo, CUDA toolkit (optional)
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
$TARGET_TRIPLE = "x86_64-pc-windows-msvc"

Write-Host ""
Write-Host "  VOXIS V4.0.0 DENSE — Windows Build (Tauri)" -ForegroundColor Cyan
Write-Host "  Glass Stone LLC © 2026" -ForegroundColor Cyan
Write-Host "  Target: $TARGET_TRIPLE" -ForegroundColor Cyan
Write-Host ""

# ── Preflight ─────────────────────────────────────────────────────────────────
Write-Host "[1/4] Checking prerequisites..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python not found. Install Python 3.11 from python.org"
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust/Cargo not found. Install from https://rustup.rs"
}
$pyVer = python --version 2>&1
Write-Host "      Python: $pyVer" -ForegroundColor Green
$cargoVer = cargo --version 2>&1
Write-Host "      Cargo: $cargoVer" -ForegroundColor Green

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

    # Install all Windows dependencies
    python -m pip install -r "$ROOT\requirements_win.txt"
    python -m pip install pyinstaller
    Write-Host "      Dependencies installed." -ForegroundColor Green
} else {
    Write-Host "[2/4] Skipping Python deps (-SkipPythonDeps)." -ForegroundColor Gray
}

# ── Build frozen binary ───────────────────────────────────────────────────────
Write-Host "[3/4] Building Trinity V8.2 Engine (PyInstaller)..." -ForegroundColor Yellow
Set-Location $ROOT
pyinstaller --noconfirm --clean trinity_v8_core_win.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }
Write-Host "      Binary built." -ForegroundColor Green

# ── Stage output for Tauri sidecar ────────────────────────────────────────────
Write-Host "[4/4] Staging sidecar for Tauri..." -ForegroundColor Yellow
$binDir = "$ROOT\app\src-tauri\binaries"
if (-not (Test-Path $binDir)) { New-Item -ItemType Directory -Path $binDir | Out-Null }
$sidecarName = "trinity_v8_core-$TARGET_TRIPLE.exe"
Copy-Item "$ROOT\dist\trinity_v8_core.exe" "$binDir\$sidecarName" -Force
Write-Host "      Staged → $binDir\$sidecarName" -ForegroundColor Green

Write-Host ""
Write-Host "  Build complete! Next steps:" -ForegroundColor Cyan
Write-Host "  1. Ensure FFmpeg is in PATH (or install via winget/scoop)" -ForegroundColor White
Write-Host "  2. Run: cd app && npm run tauri:build:win" -ForegroundColor White
Write-Host ""
