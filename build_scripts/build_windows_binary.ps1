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

# ── Build/download PhaseLimiter binary (pre-bundle) ──────────────────────────
Write-Host "[3/5] Checking PhaseLimiter mastering binary..." -ForegroundColor Yellow
$plBin = Join-Path $ROOT "trinity_engine\modules\external\phase\bin\Release\phase_limiter.exe"
if (-not (Test-Path $plBin)) {
    Write-Host "      Downloading PhaseLimiter v0.2.0 from GitHub releases..." -ForegroundColor Gray
    $plUrl = "https://github.com/ai-mastering/phaselimiter/releases/download/v0.2.0/phaselimiter-win.zip"
    $plZip = Join-Path $env:TEMP "phaselimiter-win.zip"
    $plExtract = Join-Path $env:TEMP "phaselimiter-extract"

    try {
        Invoke-WebRequest -Uri $plUrl -OutFile $plZip -UseBasicParsing
        Expand-Archive -Path $plZip -DestinationPath $plExtract -Force

        # Find phase_limiter.exe in extracted archive
        $found = Get-ChildItem -Path $plExtract -Recurse -Filter "phase_limiter.exe" | Select-Object -First 1
        if ($found) {
            $plDir = Split-Path $plBin
            New-Item -ItemType Directory -Force -Path $plDir | Out-Null
            Copy-Item $found.FullName $plBin -Force
            Write-Host "      PhaseLimiter installed → $plBin" -ForegroundColor Green

            # Copy resource/ dir if present
            $resDir = Get-ChildItem -Path $plExtract -Recurse -Directory -Filter "resource" | Select-Object -First 1
            if ($resDir) {
                $dstRes = Join-Path $ROOT "trinity_engine\modules\external\phase\resource"
                if (-not (Test-Path $dstRes)) {
                    Copy-Item $resDir.FullName $dstRes -Recurse -Force
                    Write-Host "      Resource dir copied." -ForegroundColor Green
                }
            }
        } else {
            Write-Host "      WARNING: phase_limiter.exe not found in archive." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "      WARNING: PhaseLimiter download failed: $_" -ForegroundColor Yellow
        Write-Host "      Stage 7 will use Harman/Pedalboard fallback." -ForegroundColor Yellow
    } finally {
        Remove-Item $plZip -Force -ErrorAction SilentlyContinue
        Remove-Item $plExtract -Recurse -Force -ErrorAction SilentlyContinue
    }
} else {
    $sizeMB = [math]::Round((Get-Item $plBin).Length / 1MB, 1)
    Write-Host "      PhaseLimiter already exists ($sizeMB MB)" -ForegroundColor Green
}

# ── Build frozen binary ───────────────────────────────────────────────────────
Write-Host "[4/5] Building Trinity V8.2 Engine (PyInstaller)..." -ForegroundColor Yellow
Set-Location $ROOT
pyinstaller --noconfirm --clean trinity_v8_core_win.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }
Write-Host "      Binary built." -ForegroundColor Green

# ── Stage output for Tauri sidecar ────────────────────────────────────────────
Write-Host "[5/5] Staging sidecar for Tauri..." -ForegroundColor Yellow
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
