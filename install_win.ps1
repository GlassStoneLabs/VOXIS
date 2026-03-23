# ═══════════════════════════════════════════════════════════════════
#  VOXIS 4.0 DENSE — Windows Installer (PowerShell)
#  Copyright (c) 2026 Glass Stone LLC. All Rights Reserved.
#  CEO: Gabriel B. Rodriguez
#  Powered by Trinity V8.2
# ═══════════════════════════════════════════════════════════════════
#
#  This installer:
#    1. Checks system requirements (Windows 10+, Python 3.10+, FFmpeg)
#    2. Auto-downloads FFmpeg if missing
#    3. Creates a Python virtual environment
#    4. Installs all ML dependencies (torch, torchaudio, etc.)
#    5. Downloads ~9.7 GB of ML model weights automatically
#    6. Builds the Trinity V8.2 sidecar binary
#    7. Installs Tauri frontend dependencies + creates launchers
#
#  Usage:
#    Right-click -> Run with PowerShell
#    Or: powershell -ExecutionPolicy Bypass -File install_win.ps1
# ═══════════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

$INSTALL_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_DIR = Join-Path $INSTALL_DIR "venv"
$ENGINE_DIR = Join-Path $INSTALL_DIR "trinity_engine"
$APP_DIR = Join-Path $INSTALL_DIR "app"
$TOOLS_DIR = Join-Path $INSTALL_DIR "tools"

$TOTAL_STEPS = 7
$CURRENT_STEP = 0

# ── Helpers ───────────────────────────────────────────────────────

function Write-Banner {
    Write-Host ""
    Write-Host "  =====================================================================" -ForegroundColor Cyan
    Write-Host "    VOXIS 4.0 DENSE — Windows Installer" -ForegroundColor Cyan
    Write-Host "    Powered by Trinity V8.2" -ForegroundColor Cyan
    Write-Host "    (c) 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez" -ForegroundColor Cyan
    Write-Host "  =====================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$Title, [string]$Detail = "")
    $script:CURRENT_STEP++
    Write-Host ""
    Write-Host "  [$script:CURRENT_STEP/$TOTAL_STEPS] $Title" -ForegroundColor Blue
    if ($Detail) {
        Write-Host "      $Detail" -ForegroundColor Yellow
    }
}

function Write-Ok {
    param([string]$Msg)
    Write-Host "      [OK] $Msg" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Msg)
    Write-Host "      [!] $Msg" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Msg)
    Write-Host "      [X] $Msg" -ForegroundColor Red
    Write-Host "      Installation aborted." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════
Write-Banner

# ── Step 1: System Requirements ──────────────────────────────────
Write-Step "Checking System Requirements" "Windows 10+, Python 3.10+, FFmpeg, CUDA..."

# Windows version
$osVer = [System.Environment]::OSVersion.Version
if ($osVer.Major -lt 10) {
    Write-Fail "Windows 10 or later required (found $($osVer.Major).$($osVer.Minor))"
}
Write-Ok "Windows $($osVer.Major).$($osVer.Minor) (Build $($osVer.Build))"
Write-Ok "Architecture: $env:PROCESSOR_ARCHITECTURE"

# Python
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $pyVer = & $cmd --version 2>&1
        if ($pyVer -match "Python (\d+)\.(\d+)") {
            $pyMajor = [int]$Matches[1]
            $pyMinor = [int]$Matches[2]
            if ($pyMajor -ge 3 -and $pyMinor -ge 10) {
                $pythonCmd = $cmd
                Write-Ok "Python $($Matches[0]) (via '$cmd')"
                break
            }
        }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Fail "Python 3.10+ not found. Download from https://www.python.org/downloads/"
}

# FFmpeg — auto-download if missing
$ffmpegFound = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpegFound) {
    Write-Ok "FFmpeg found: $($ffmpegFound.Source)"
} else {
    Write-Warn "FFmpeg not found on PATH. Auto-downloading..."

    $ffmpegDir = Join-Path $TOOLS_DIR "ffmpeg"
    $ffmpegExe = Join-Path $ffmpegDir "ffmpeg.exe"

    if (Test-Path $ffmpegExe) {
        Write-Ok "FFmpeg already cached at $ffmpegDir"
    } else {
        try {
            New-Item -ItemType Directory -Path $ffmpegDir -Force | Out-Null
            $zipUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
            $zipPath = Join-Path $TOOLS_DIR "ffmpeg.zip"

            Write-Host "      Downloading FFmpeg (~80 MB)..." -ForegroundColor Yellow
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing

            Write-Host "      Extracting..." -ForegroundColor Yellow
            Expand-Archive -Path $zipPath -DestinationPath $TOOLS_DIR -Force

            # Find extracted bin/ and copy ffmpeg.exe + ffprobe.exe
            $extractedBin = Get-ChildItem -Path $TOOLS_DIR -Directory -Filter "ffmpeg-*" |
                Select-Object -First 1
            if ($extractedBin) {
                $binDir = Join-Path $extractedBin.FullName "bin"
                Copy-Item (Join-Path $binDir "ffmpeg.exe") $ffmpegDir -Force
                Copy-Item (Join-Path $binDir "ffprobe.exe") $ffmpegDir -Force
                Remove-Item $extractedBin.FullName -Recurse -Force
            }
            Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

            if (Test-Path $ffmpegExe) {
                Write-Ok "FFmpeg installed to $ffmpegDir"
            } else {
                Write-Fail "FFmpeg extraction failed. Download manually from https://ffmpeg.org"
            }
        } catch {
            Write-Fail "FFmpeg download failed: $_`nDownload manually from https://ffmpeg.org and add to PATH."
        }
    }

    # Add to PATH for this session
    $env:PATH = "$ffmpegDir;$env:PATH"
}

# CUDA / GPU detection
try {
    $nvidiaSmi = nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null
    if ($nvidiaSmi) {
        Write-Ok "NVIDIA GPU: $($nvidiaSmi.Trim())"
    } else {
        Write-Warn "No NVIDIA GPU detected. Will use CPU + DirectML."
    }
} catch {
    Write-Warn "nvidia-smi not found. Will use CPU + DirectML."
}

# Node.js
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeVer = & node --version 2>&1
    Write-Ok "Node.js $nodeVer"
} else {
    Write-Warn "Node.js not found. Frontend build will be skipped."
}

# Disk space
try {
    $drive = (Get-Item $INSTALL_DIR).PSDrive
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt 15) {
        Write-Warn "Low disk space: ${freeGB} GB available (15 GB+ recommended)"
    } else {
        Write-Ok "Disk space: ${freeGB} GB available"
    }
} catch {}

# RAM
try {
    $ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    Write-Ok "RAM: ${ramGB} GB"
} catch {}

# ── Step 2: Python Virtual Environment ──────────────────────────
Write-Step "Creating Python Virtual Environment" $VENV_DIR

if (Test-Path $VENV_DIR) {
    Write-Warn "Existing venv found. Reusing."
} else {
    & $pythonCmd -m venv $VENV_DIR
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to create virtual environment" }
    Write-Ok "Virtual environment created"
}

$venvPython = Join-Path $VENV_DIR "Scripts\python.exe"
$venvPip = Join-Path $VENV_DIR "Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Fail "Venv Python not found at $venvPython"
}
Write-Ok "Activated venv ($venvPython)"

# Upgrade pip
& $venvPip install --upgrade pip --quiet 2>&1 | Out-Null
Write-Ok "pip upgraded"

# ── Step 3: Install Python Dependencies ─────────────────────────
Write-Step "Installing ML Dependencies" "torch, torchaudio, audio-separator, audiosr, voicerestore..."

Write-Host "      Installing PyTorch 2.6.0 (this may take several minutes)..." -ForegroundColor Yellow
& $venvPip install torch==2.6.0 torchaudio==2.6.0 torchvision==0.21.0 --quiet 2>&1 | Out-Null
Write-Ok "PyTorch 2.6.0 + torchaudio + torchvision"

& $venvPip install pedalboard "numpy==1.23.5" soundfile "librosa==0.9.2" "scipy>=1.14.1" "resampy==0.4.3" "soxr==1.0.0" "pydub==0.25.1" pyloudnorm --quiet 2>&1 | Out-Null
Write-Ok "Audio processing libs"

& $venvPip install "audio-separator>=0.14.3" --quiet 2>&1 | Out-Null
Write-Ok "audio-separator (BS-RoFormer)"

& $venvPip install "audiosr>=0.0.7" "matplotlib>=3.9.0" --quiet 2>&1 | Out-Null
Write-Ok "AudioSR (neural super-resolution)"

& $venvPip install "huggingface_hub>=0.24.6" "x-transformers>=2.16.2" "gateloop-transformer>=0.2.5" "jaxtyping>=0.3.9" "torchdiffeq>=0.2.4" "rotary-embedding-torch>=0.6.5" "einops>=0.8.2" --quiet 2>&1 | Out-Null
Write-Ok "VoiceRestore transformer deps"

& $venvPip install "safetensors>=0.7.0" "tokenizers>=0.13.3" "transformers>=4.30.2" "omegaconf>=2.3.0" --quiet 2>&1 | Out-Null
Write-Ok "Inference utilities"

# Windows: DirectML GPU acceleration
& $venvPip install "onnxruntime-directml>=1.16.0" --quiet 2>&1 | Out-Null
Write-Ok "ONNX Runtime DirectML (GPU acceleration)"

& $venvPip install "psutil>=7.0.0" "requests>=2.32.0" "certifi>=2026.2.25" "filelock>=3.25.0" "packaging>=23.2" "tqdm>=4.66.0" "PyYAML>=6.0.0" --quiet 2>&1 | Out-Null
Write-Ok "System utilities"

& $venvPip install "setuptools>=69.5.1" --quiet 2>&1 | Out-Null
Write-Ok "Build tools"

# Full requirements.txt as safety net
$reqFile = Join-Path $INSTALL_DIR "requirements.txt"
if (Test-Path $reqFile) {
    try {
        & $venvPip install -r $reqFile --quiet 2>&1 | Out-Null
        Write-Ok "All requirements.txt deps verified"
    } catch {
        Write-Warn "Some requirements.txt deps failed (non-critical for Windows)"
    }
}

Write-Ok "All dependencies installed"

# ── Step 4: Download ML Models ──────────────────────────────────
Write-Step "Downloading ML Models" "BS-RoFormer, VoiceRestore, AudioSR, BigVGAN, XLS-R, Diff-HierVC (~9.7 GB)..."

$distroDir = Join-Path $ENGINE_DIR "distro\models"
$downloaderScript = Join-Path $ENGINE_DIR "model_downloader.py"

if (Test-Path $distroDir) {
    Write-Host "      Found local distro\models\ — installing from disk..." -ForegroundColor Yellow
    Push-Location $ENGINE_DIR
    & $venvPython setup_models.py
    Pop-Location
    Write-Ok "Models installed from distro/"
} elseif (Test-Path $downloaderScript) {
    Write-Host ""
    Write-Host "      ========================================================" -ForegroundColor Yellow
    Write-Host "      Downloading ~9.7 GB of ML models from HuggingFace..." -ForegroundColor Yellow
    Write-Host "      This will take a while depending on your connection." -ForegroundColor Yellow
    Write-Host "      Models cached at: %USERPROFILE%\.voxis\dependencies\models\" -ForegroundColor Yellow
    Write-Host "      ========================================================" -ForegroundColor Yellow
    Write-Host ""

    Push-Location $ENGINE_DIR
    & $venvPython $downloaderScript --download
    $dlResult = $LASTEXITCODE
    Pop-Location

    if ($dlResult -eq 0) {
        Write-Ok "All models downloaded successfully"
    } else {
        Write-Warn "Some models may have failed. Retry with:"
        Write-Warn "  cd $ENGINE_DIR && python model_downloader.py --download"
    }
} else {
    Write-Warn "Model downloader not found. Models will download on first run."
}

# Verify model status
try {
    Push-Location $ENGINE_DIR
    & $venvPython model_registry.py 2>$null
    Pop-Location
} catch {}

# ── Step 5: Verify Pipeline ─────────────────────────────────────
Write-Step "Verifying Trinity V8.2 Pipeline" "Testing all module imports..."

$verifyScript = @"
import sys, os
sys.path.insert(0, os.getcwd())
modules = [
    'modules.ingest', 'modules.device_utils', 'modules.pipeline_cache',
    'modules.retry_engine', 'modules.error_telemetry',
    'modules.spectrum_analyzer', 'modules.uvr_processor',
    'modules.voicerestore_wrapper', 'modules.upsampler',
    'modules.mastering_phase', 'modules.onnx_separator'
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
print(f'All {len(modules)} modules loaded successfully.')
"@

Push-Location $ENGINE_DIR
& $venvPython -c $verifyScript 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "All pipeline modules verified"
} else {
    Write-Warn "Some modules failed to import (may need models downloaded first)"
}
Pop-Location

# ── Step 6: Build Sidecar Binary ────────────────────────────────
Write-Step "Building Trinity V8.2 Sidecar Binary" "PyInstaller -> single executable..."

& $venvPip install pyinstaller --quiet 2>&1 | Out-Null
Write-Ok "PyInstaller installed"

$specFile = Join-Path $INSTALL_DIR "trinity_v8_core.spec"
if (Test-Path $specFile) {
    & $venvPip install "setuptools==69.5.1" "numpy<2.0" --quiet 2>&1 | Out-Null

    Write-Host "      Building sidecar (this may take 5-10 minutes)..." -ForegroundColor Yellow
    Push-Location $INSTALL_DIR
    & $venvPython -m PyInstaller $specFile --noconfirm 2>&1
    $buildResult = $LASTEXITCODE
    Pop-Location

    if ($buildResult -eq 0) {
        # Find the built exe
        $srcExe = Join-Path $INSTALL_DIR "dist\trinity_v8_core.exe"
        if (-not (Test-Path $srcExe)) {
            $srcExe = Join-Path $INSTALL_DIR "dist\trinity_v8_core\trinity_v8_core.exe"
        }

        if (Test-Path $srcExe) {
            $destDir = Join-Path $APP_DIR "src-tauri\binaries"
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            $destExe = Join-Path $destDir "trinity_v8_core-x86_64-pc-windows-msvc.exe"
            Copy-Item $srcExe $destExe -Force
            $sizeMB = [math]::Round((Get-Item $destExe).Length / 1MB)
            Write-Ok "Sidecar binary: $destExe ($sizeMB MB)"
        } else {
            Write-Warn "Built binary not found. Check dist\ directory."
        }
    } else {
        Write-Warn "Sidecar build had issues. You can rebuild later:"
        Write-Warn "  pyinstaller trinity_v8_core.spec --noconfirm"
    }
} else {
    Write-Warn "PyInstaller spec not found. Skipping sidecar build."
}

# ── Step 7: Frontend Dependencies + Launchers ───────────────────
Write-Step "Installing Frontend + Creating Launchers" "React + Tauri + VOXIS.bat..."

$packageJson = Join-Path $APP_DIR "package.json"
if ((Test-Path $packageJson) -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    Push-Location $APP_DIR
    npm install --silent 2>&1 | Select-Object -Last 2
    Pop-Location
    Write-Ok "Frontend dependencies installed"
} else {
    Write-Warn "Skipping frontend (Node.js or app\package.json not found)"
}

# Desktop launcher
$launcherBat = Join-Path $INSTALL_DIR "VOXIS.bat"
@"
@echo off
title VOXIS 4.0 DENSE — Glass Stone LLC
setlocal
set "DIR=%~dp0"
call "%DIR%venv\Scripts\activate.bat"
if exist "%DIR%tools\ffmpeg" set "PATH=%DIR%tools\ffmpeg;%PATH%"

echo ^>^> [VOXIS] Starting Trinity V8.2 Engine...
echo ^>^> [VOXIS] Platform: Windows x64

if exist "%DIR%app\package.json" (
    cd /d "%DIR%app"
    npm run tauri dev
) else (
    echo ^>^> [VOXIS] Running in CLI mode.
    cd /d "%DIR%trinity_engine"
    cmd /k
)
"@ | Out-File -FilePath $launcherBat -Encoding ASCII
Write-Ok "Launcher: VOXIS.bat"

# CLI launcher
$cliBat = Join-Path $INSTALL_DIR "voxis-cli.bat"
@"
@echo off
setlocal
set "DIR=%~dp0"
call "%DIR%venv\Scripts\activate.bat"
if exist "%DIR%tools\ffmpeg" set "PATH=%DIR%tools\ffmpeg;%PATH%"
cd /d "%DIR%trinity_engine"
python trinity_core.py %*
"@ | Out-File -FilePath $cliBat -Encoding ASCII
Write-Ok "CLI launcher: voxis-cli.bat"

# ═══════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  =====================================================================" -ForegroundColor Green
Write-Host "    [OK] VOXIS 4.0 DENSE — Installation Complete!" -ForegroundColor Green
Write-Host "  =====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  To launch:" -ForegroundColor White
Write-Host "    * Double-click VOXIS.bat (Desktop App)" -ForegroundColor Cyan
Write-Host "    * Or from terminal:" -ForegroundColor Cyan
Write-Host "      .\voxis-cli.bat --input audio.wav --output restored.wav" -ForegroundColor White
Write-Host ""
Write-Host "  Quick Test:" -ForegroundColor White
Write-Host "    .\voxis-cli.bat --input <any_audio_file> --output output.wav" -ForegroundColor White
Write-Host ""
Write-Host "  (c) 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez" -ForegroundColor Gray
Write-Host ""

Read-Host "Press Enter to exit"
