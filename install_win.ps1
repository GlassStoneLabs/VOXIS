# ═══════════════════════════════════════════════════════════════════
#  VOXIS 4.0 DENSE — Windows Installer
#  Copyright © 2026 Glass Stone LLC. All Rights Reserved.
#  CEO: Gabriel B. Rodriguez
#  Powered by Trinity V8.2
# ═══════════════════════════════════════════════════════════════════
#
#  This installer:
#    1. Checks system requirements (Windows 10+, Python 3.10+, FFmpeg)
#    2. Creates a Python virtual environment
#    3. Installs all ML dependencies (torch+CUDA, torchaudio, etc.)
#    4. Restores model weights from distro/ (~12 GB)
#    5. Creates desktop launcher scripts
#
#  Usage:
#    Right-click → "Run with PowerShell"
#    Or: powershell -ExecutionPolicy Bypass -File install_win.ps1
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

$INSTALL_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_DIR = Join-Path $INSTALL_DIR "venv"
$ENGINE_DIR = Join-Path $INSTALL_DIR "trinity_engine"
$APP_DIR = Join-Path $INSTALL_DIR "app"

function Banner {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║  VOXIS 4.0 DENSE — Windows Installer                   ║" -ForegroundColor Cyan
    Write-Host "  ║  Powered by Trinity V8.2                                ║" -ForegroundColor Cyan
    Write-Host "  ║  © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez     ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Step($num, $total, $title, $desc) {
    Write-Host ""
    Write-Host "  [$num/$total] $title" -ForegroundColor Blue -NoNewline
    Write-Host ""
    Write-Host "         $desc" -ForegroundColor Yellow
}

function Ok($msg) { Write-Host "         ✓ $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "         ⚠ $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host "         ✗ $msg" -ForegroundColor Red
    Write-Host "         Installation aborted." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$TOTAL = 7

# ═══════════════════════════════════════════════════════════════════
Banner

# ── Step 1: System Requirements ──────────────────────────────────
Step 1 $TOTAL "Checking System Requirements" "Windows 10+, Python 3.10+, FFmpeg, CUDA..."

# Check Windows version
$osVersion = [Environment]::OSVersion.Version
if ($osVersion.Major -lt 10) { Fail "Windows 10+ required" }
Ok "Windows $($osVersion.Major).$($osVersion.Minor)"

# Check architecture
$arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
Ok "Architecture: $arch"

# Check Python
try {
    $pyVersion = (python --version 2>&1).ToString().Split(" ")[1]
    $pyParts = $pyVersion.Split(".")
    if ([int]$pyParts[0] -ge 3 -and [int]$pyParts[1] -ge 10) {
        Ok "Python $pyVersion"
    } else {
        Fail "Python 3.10+ required (found $pyVersion)"
    }
} catch {
    Fail "Python not found. Install from https://www.python.org/downloads/"
}

# Check FFmpeg
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Ok "FFmpeg found"
} else {
    Warn "FFmpeg not found."
    Warn "Install with: choco install ffmpeg  (or download from ffmpeg.org)"
    Warn "Continuing anyway — FFmpeg is required at runtime."
}

# Check CUDA
try {
    $nvidiaSmi = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null
    if ($nvidiaSmi) {
        Ok "NVIDIA GPU: $($nvidiaSmi.Trim())"
    } else {
        Warn "No NVIDIA GPU detected. Will use CPU (slower)."
    }
} catch {
    Warn "nvidia-smi not found. Will use CPU."
}

# ── Step 2: Python Virtual Environment ──────────────────────────
Step 2 $TOTAL "Creating Python Virtual Environment" "$VENV_DIR"

if (Test-Path $VENV_DIR) {
    Warn "Existing venv found. Reusing."
} else {
    python -m venv $VENV_DIR
    Ok "Virtual environment created"
}

$activateScript = Join-Path $VENV_DIR "Scripts\Activate.ps1"
& $activateScript
Ok "Activated venv"

# Upgrade pip
python -m pip install --upgrade pip --quiet
Ok "pip upgraded"

# ── Step 3: Install Python Dependencies ─────────────────────────
Step 3 $TOTAL "Installing ML Dependencies" "torch+CUDA, torchaudio, audio-separator, deepfilternet, audiosr, voicerestore..."

# Manual sequential install to avoid strict dependency resolver conflicts
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
pip install pedalboard numpy soundfile librosa --quiet

# Source separation + audio super-resolution
pip install "audio-separator[cpu]>=0.41.0" audiosr matplotlib --quiet

# VoiceRestore (Transformer-Diffusion) + all transitive deps
pip install huggingface_hub x-transformers gateloop-transformer jaxtyping torchdiffeq rotary-embedding-torch --quiet

# ONNX + DirectML GPU acceleration (Windows)
pip install onnxruntime onnxruntime-directml "scikit-learn==1.5.1" --quiet

# System & telemetry
pip install requests psutil --quiet

# Install remaining dependencies from requirements_win.txt if present
$reqWin = Join-Path $INSTALL_DIR "requirements_win.txt"
if (Test-Path $reqWin) {
    pip install -r $reqWin --quiet
    Ok "requirements_win.txt dependencies installed"
}

Ok "All dependencies installed"

# ── Step 4: Install Models ──────────────────────────────────────
Step 4 $TOTAL "Installing ML Models" "BS-RoFormer, VoiceRestore, AudioSR (~13 GB)..."

$distroModels = Join-Path $ENGINE_DIR "distro\models"
if (Test-Path $distroModels) {
    Set-Location $ENGINE_DIR
    python setup_models.py
    Ok "Models installed from distro/"
} else {
    Warn "distro\models\ not found. Models will download on first run (~12GB)."
}

# ── Step 5: Verify Pipeline ─────────────────────────────────────
Step 5 $TOTAL "Verifying Trinity V8.2 Pipeline" "Testing all module imports..."

Set-Location $ENGINE_DIR
$testResult = python -c @"
import sys
modules = [
    'modules.ingest', 'modules.device_utils', 'modules.pipeline_cache',
    'modules.retry_engine', 'modules.error_telemetry',
    'modules.spectrum_analyzer', 'modules.uvr_processor',
    'modules.voicerestore_wrapper', 'modules.upsampler',
    'modules.mastering_phase', 'modules.adaptive_chunker',
    'modules.path_utils', 'modules.onnx_bridge'
]
failed = 0
for m in modules:
    try:
        __import__(m)
    except Exception as e:
        print(f'  FAIL: {m}: {e}')
        failed += 1
if failed > 0:
    sys.exit(1)
print(f'  All {len(modules)} modules loaded successfully.')
"@ 2>&1

if ($LASTEXITCODE -ne 0) { Fail "Module verification failed" }
Ok "All pipeline modules verified"

# ── Step 6: Install Frontend Dependencies ───────────────────────
Step 6 $TOTAL "Installing Frontend Dependencies" "React + Tauri..."

if ((Get-Command npm -ErrorAction SilentlyContinue) -and (Test-Path $APP_DIR)) {
    Set-Location $APP_DIR
    npm install --silent 2>$null
    Ok "Frontend dependencies installed"
} else {
    Warn "Skipping frontend (Node.js or app\ not found)"
}

# ── Step 7: Create Launchers ────────────────────────────────────
Step 7 $TOTAL "Creating Desktop Launchers" "VOXIS.bat, voxis-cli.bat..."

# Desktop launcher
$launcherPath = Join-Path $INSTALL_DIR "VOXIS.bat"
@"
@echo off
title VOXIS 4.0 DENSE — Glass Stone LLC
cd /d "%~dp0"
call venv\Scripts\activate.bat
set PYTORCH_ENABLE_MPS_FALLBACK=1
echo [VOXIS] Starting Trinity V8.2 Engine...
if exist "app\package.json" (
    cd app
    npm run tauri dev
) else (
    echo [VOXIS] Running in CLI mode.
    cd trinity_engine
    cmd /k
)
"@ | Out-File -Encoding ASCII $launcherPath
Ok "Launcher: VOXIS.bat"

# CLI launcher
$cliPath = Join-Path $INSTALL_DIR "voxis-cli.bat"
@"
@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
set PYTORCH_ENABLE_MPS_FALLBACK=1
cd trinity_engine
python trinity_core.py %*
"@ | Out-File -Encoding ASCII $cliPath
Ok "CLI: voxis-cli.bat"

# ═══════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║  ✓ VOXIS 4.0 DENSE — Installation Complete!            ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  To launch:" -ForegroundColor White
Write-Host "    • Double-click VOXIS.bat (Desktop App)" -ForegroundColor Cyan
Write-Host "    • Or from terminal:" -ForegroundColor Cyan
Write-Host "      .\voxis-cli.bat --input audio.wav --output restored.wav" -ForegroundColor Cyan
Write-Host ""
Write-Host "  © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez" -ForegroundColor Gray
Write-Host ""

Read-Host "Press Enter to exit"
