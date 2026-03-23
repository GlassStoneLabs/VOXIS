#!/usr/bin/env python3
"""
VOXIS V4.0.0 DENSE — Cross-Platform Installer
Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez

Auto-installs Python venv, all pip dependencies, downloads ~9.7 GB of ML
models (BS-RoFormer, VoiceRestore, AudioSR, BigVGAN, XLS-R, Diff-HierVC),
builds the PyInstaller sidecar binary, and installs the Tauri frontend.

Supports: macOS (arm64/x86_64) and Windows (x64).

Usage:
    python3 install.py              # Full install
    python3 install.py --models     # Download models only
    python3 install.py --deps       # Install Python deps only
    python3 install.py --build      # Build sidecar binary only
    python3 install.py --check      # Verify installation
    python3 install.py --no-models  # Skip model download (do everything else)
"""

import os
import sys
import shutil
import platform
import subprocess
import json
import time
import argparse
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────

INSTALL_DIR = Path(__file__).resolve().parent
ENGINE_DIR = INSTALL_DIR / "trinity_engine"
APP_DIR = INSTALL_DIR / "app"
VENV_DIR = INSTALL_DIR / "venv"

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
ARCH = platform.machine()

PYTHON = "python" if IS_WINDOWS else "python3"
PIP = None  # Set after venv creation

MIN_PYTHON = (3, 10)
MIN_DISK_GB = 15
TOTAL_MODEL_SIZE_GB = 9.7

# Tauri sidecar target triples
TARGET_TRIPLE = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Windows", "AMD64"): "x86_64-pc-windows-msvc",
    ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
}

# ── Colors (ANSI, disabled on Windows unless modern terminal) ─────────────

if IS_WINDOWS:
    # Enable ANSI on Windows 10+
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        HAS_COLOR = True
    except Exception:
        HAS_COLOR = False
else:
    HAS_COLOR = True

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if HAS_COLOR else text

RED    = lambda t: _c("0;31", t)
GREEN  = lambda t: _c("0;32", t)
YELLOW = lambda t: _c("1;33", t)
BLUE   = lambda t: _c("0;34", t)
CYAN   = lambda t: _c("0;36", t)
BOLD   = lambda t: _c("1", t)

# ── Logging ───────────────────────────────────────────────────────────────

TOTAL_STEPS = 7
_current_step = 0

def banner():
    print()
    print(CYAN("╔══════════════════════════════════════════════════════════════╗"))
    print(CYAN("║") + "  " + BOLD("VOXIS 4.0 DENSE") + " — Cross-Platform Installer               " + CYAN("║"))
    print(CYAN("║") + "  Powered by Trinity V8.2                                    " + CYAN("║"))
    print(CYAN("║") + "  © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez         " + CYAN("║"))
    print(CYAN("╚══════════════════════════════════════════════════════════════╝"))
    print()

def step(title, detail=""):
    global _current_step
    _current_step += 1
    print(f"\n{BLUE(f'[{_current_step}/{TOTAL_STEPS}]')} {BOLD(title)}")
    if detail:
        print(f"    {YELLOW(detail)}")

def ok(msg):
    print(f"    {GREEN('✓')} {msg}")

def warn(msg):
    print(f"    {YELLOW('⚠')} {msg}")

def fail(msg):
    print(f"    {RED('✗')} {msg}")
    print(f"    {RED('Installation aborted.')}")
    sys.exit(1)

def run(cmd, **kwargs):
    """Run a subprocess, return CompletedProcess. Raises on failure unless check=False."""
    kwargs.setdefault("check", True)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.CalledProcessError as e:
        if kwargs.get("check"):
            print(f"    Command failed: {' '.join(str(c) for c in cmd)}")
            if e.stdout:
                print(f"    stdout: {e.stdout[:500]}")
            if e.stderr:
                print(f"    stderr: {e.stderr[:500]}")
            raise
        return e
    except FileNotFoundError:
        return None

def pip_install(*packages, quiet=True):
    """Install pip packages into the venv."""
    cmd = [str(PIP), "install"] + list(packages)
    if quiet:
        cmd.append("--quiet")
    run(cmd)

# ── Step 1: System Requirements ───────────────────────────────────────────

def check_system():
    step("Checking System Requirements",
         f"{platform.system()} {ARCH}, Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, FFmpeg...")

    # OS
    if IS_MACOS:
        try:
            ver = subprocess.check_output(["sw_vers", "-productVersion"], text=True).strip()
            major = int(ver.split(".")[0])
            if major < 12:
                fail(f"macOS 12+ required (found {ver})")
            ok(f"macOS {ver}")
        except Exception:
            warn("Could not determine macOS version")
    elif IS_WINDOWS:
        ver = platform.version()
        ok(f"Windows {platform.release()} (build {ver})")
    elif IS_LINUX:
        ok(f"Linux {platform.release()}")
    else:
        warn(f"Untested platform: {platform.system()}")

    ok(f"Architecture: {ARCH}")

    # Python
    py_ver = sys.version_info
    if py_ver >= MIN_PYTHON:
        ok(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
    else:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required "
             f"(found {py_ver.major}.{py_ver.minor}). Install from python.org")

    # FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            ff_ver = subprocess.check_output(
                ["ffmpeg", "-version"], text=True, stderr=subprocess.STDOUT
            ).split("\n")[0]
            ok(f"FFmpeg found: {ff_ver.split(' ')[2] if len(ff_ver.split(' ')) > 2 else 'installed'}")
        except Exception:
            ok("FFmpeg found")
    else:
        if IS_MACOS:
            warn("FFmpeg not found. Attempting install via Homebrew...")
            if shutil.which("brew"):
                try:
                    run(["brew", "install", "ffmpeg"])
                    ok("FFmpeg installed via Homebrew")
                except Exception:
                    fail("Failed to install FFmpeg. Run: brew install ffmpeg")
            else:
                fail("FFmpeg required. Install Homebrew first, then: brew install ffmpeg")
        elif IS_WINDOWS:
            warn("FFmpeg not found on PATH.")
            _install_ffmpeg_windows()
        else:
            fail("FFmpeg required. Install via your package manager (apt install ffmpeg)")

    # Node.js
    node_path = shutil.which("node")
    if node_path:
        try:
            node_ver = subprocess.check_output(["node", "--version"], text=True).strip()
            ok(f"Node.js {node_ver}")
        except Exception:
            ok("Node.js found")
    else:
        warn("Node.js not found. Frontend build will be skipped.")

    # Disk space
    try:
        usage = shutil.disk_usage(str(INSTALL_DIR))
        avail_gb = usage.free / (1024 ** 3)
        if avail_gb < MIN_DISK_GB:
            warn(f"Low disk space: {avail_gb:.1f} GB available ({MIN_DISK_GB} GB+ recommended)")
        else:
            ok(f"Disk space: {avail_gb:.0f} GB available")
    except Exception:
        warn("Could not determine disk space")

    # RAM
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        ok(f"RAM: {ram_gb:.0f} GB")
    except ImportError:
        try:
            if IS_MACOS:
                mem = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
                ok(f"RAM: {mem / (1024**3):.0f} GB")
            elif IS_WINDOWS:
                r = run(["wmic", "computersystem", "get", "TotalPhysicalMemory", "/value"], check=False)
                if r and r.stdout:
                    for line in r.stdout.strip().split("\n"):
                        if "TotalPhysicalMemory" in line:
                            mem = int(line.split("=")[1])
                            ok(f"RAM: {mem / (1024**3):.0f} GB")
                            break
        except Exception:
            pass


def _install_ffmpeg_windows():
    """Download and install FFmpeg on Windows."""
    ffmpeg_dir = INSTALL_DIR / "tools" / "ffmpeg"
    ffmpeg_exe = ffmpeg_dir / "ffmpeg.exe"

    if ffmpeg_exe.exists():
        ok(f"FFmpeg already at {ffmpeg_exe}")
        _add_to_path(str(ffmpeg_dir))
        return

    print("    Downloading FFmpeg for Windows...")
    try:
        import urllib.request
        import zipfile
        import io

        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        print(f"    Source: {url}")
        print("    This may take a minute...")

        with urllib.request.urlopen(url, timeout=120) as resp:
            data = resp.read()

        ffmpeg_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                if member.endswith("/bin/ffmpeg.exe"):
                    with zf.open(member) as src, open(ffmpeg_exe, "wb") as dst:
                        dst.write(src.read())
                elif member.endswith("/bin/ffprobe.exe"):
                    probe = ffmpeg_dir / "ffprobe.exe"
                    with zf.open(member) as src, open(probe, "wb") as dst:
                        dst.write(src.read())

        if ffmpeg_exe.exists():
            _add_to_path(str(ffmpeg_dir))
            ok(f"FFmpeg installed to {ffmpeg_dir}")
        else:
            fail("FFmpeg extraction failed. Download manually from https://ffmpeg.org/download.html")

    except Exception as e:
        fail(f"FFmpeg download failed: {e}\n"
             "    Download manually from https://ffmpeg.org/download.html "
             "and add to PATH.")


def _add_to_path(directory):
    """Add a directory to the current process PATH."""
    current = os.environ.get("PATH", "")
    if directory not in current:
        os.environ["PATH"] = directory + os.pathsep + current


# ── Step 2: Python Virtual Environment ────────────────────────────────────

def setup_venv():
    global PIP
    step("Creating Python Virtual Environment", str(VENV_DIR))

    if VENV_DIR.exists():
        warn("Existing venv found. Reusing.")
    else:
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        ok("Virtual environment created")

    # Determine pip/python paths inside venv
    if IS_WINDOWS:
        venv_python = VENV_DIR / "Scripts" / "python.exe"
        PIP = VENV_DIR / "Scripts" / "pip.exe"
    else:
        venv_python = VENV_DIR / "bin" / "python3"
        PIP = VENV_DIR / "bin" / "pip"

    if not PIP.exists():
        # Fallback
        PIP = VENV_DIR / "Scripts" / "pip" if IS_WINDOWS else VENV_DIR / "bin" / "pip"

    ok(f"Activated venv ({venv_python})")

    # Upgrade pip
    run([str(PIP), "install", "--upgrade", "pip", "--quiet"])
    ok("pip upgraded")


# ── Step 3: Install Python Dependencies ───────────────────────────────────

def install_deps():
    step("Installing ML Dependencies",
         "torch, torchaudio, audio-separator, audiosr, voicerestore...")

    # PyTorch (CPU-only on macOS/Windows by default; CUDA users can override)
    print("    Installing PyTorch 2.6.0 (this may take a few minutes)...")
    pip_install("torch==2.6.0", "torchaudio==2.6.0", "torchvision==0.21.0")
    ok("PyTorch 2.6.0 + torchaudio + torchvision")

    # Core audio
    pip_install("pedalboard", "numpy==1.23.5", "soundfile", "librosa==0.9.2",
                "scipy>=1.14.1", "resampy==0.4.3", "soxr==1.0.0", "pydub==0.25.1",
                "pyloudnorm")
    ok("Audio processing libs")

    # Source separation
    pip_install("audio-separator>=0.14.3")
    ok("audio-separator (BS-RoFormer)")

    # AudioSR
    pip_install("audiosr>=0.0.7", "matplotlib>=3.9.0")
    ok("AudioSR (neural super-resolution)")

    # VoiceRestore transitive deps
    pip_install("huggingface_hub>=0.24.6", "x-transformers>=2.16.2",
                "gateloop-transformer>=0.2.5", "jaxtyping>=0.3.9",
                "torchdiffeq>=0.2.4", "rotary-embedding-torch>=0.6.5",
                "einops>=0.8.2")
    ok("VoiceRestore transformer deps")

    # Inference utilities
    pip_install("safetensors>=0.7.0", "tokenizers>=0.13.3",
                "transformers>=4.30.2", "omegaconf>=2.3.0")
    ok("Inference utilities")

    # Platform-specific acceleration
    if IS_MACOS and ARCH == "arm64":
        pip_install("coremltools>=9.0", "scikit-learn==1.5.1")
        ok("CoreML + scikit-learn (Apple Neural Engine)")
        pip_install("onnxruntime>=1.24.0")
        ok("ONNX Runtime")
    elif IS_WINDOWS:
        pip_install("onnxruntime-directml>=1.16.0")
        ok("ONNX Runtime DirectML (GPU acceleration)")
    else:
        pip_install("onnxruntime>=1.24.0")
        ok("ONNX Runtime")

    # System & telemetry
    pip_install("psutil>=7.0.0", "requests>=2.32.0", "certifi>=2026.2.25",
                "filelock>=3.25.0", "packaging>=23.2", "tqdm>=4.66.0",
                "PyYAML>=6.0.0")
    ok("System utilities")

    # Build tools
    pip_install("setuptools>=69.5.1")
    ok("Build tools")

    # Full requirements.txt as safety net
    req_file = INSTALL_DIR / "requirements.txt"
    if req_file.exists():
        try:
            pip_install("-r", str(req_file))
            ok("All requirements.txt deps verified")
        except Exception:
            warn("Some requirements.txt deps failed (non-critical)")

    ok("All dependencies installed")


# ── Step 4: Download ML Models ────────────────────────────────────────────

def download_models():
    step("Downloading ML Models",
         f"~{TOTAL_MODEL_SIZE_GB} GB: BS-RoFormer, VoiceRestore, AudioSR, BigVGAN, XLS-R, Diff-HierVC...")

    # Check for local distro/ first
    distro_dir = ENGINE_DIR / "distro" / "models"
    if distro_dir.is_dir():
        print("    Found local distro/models/ — installing from disk...")
        venv_py = str(VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") /
                      ("python.exe" if IS_WINDOWS else "python3"))
        try:
            run([venv_py, str(ENGINE_DIR / "setup_models.py")],
                capture_output=False, cwd=str(ENGINE_DIR))
            ok("Models installed from distro/")
            return
        except Exception as e:
            warn(f"Local install failed ({e}), falling back to download...")

    # Download via model_downloader.py
    venv_py = str(VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") /
                  ("python.exe" if IS_WINDOWS else "python3"))

    print()
    print(f"    {'='*55}")
    print(f"    Downloading {TOTAL_MODEL_SIZE_GB} GB of ML models...")
    print(f"    This will take a while depending on your connection.")
    print(f"    Models are cached at ~/.voxis/dependencies/models/")
    print(f"    {'='*55}")
    print()

    downloader = ENGINE_DIR / "model_downloader.py"
    if not downloader.exists():
        fail(f"Model downloader not found: {downloader}")

    try:
        result = run(
            [venv_py, str(downloader), "--download"],
            capture_output=False,
            cwd=str(ENGINE_DIR),
            check=False,
        )
        if result and result.returncode == 0:
            ok("All models downloaded successfully")
        else:
            warn("Some models may have failed. You can retry with: python install.py --models")
    except Exception as e:
        warn(f"Model download encountered issues: {e}")
        warn("Retry with: python install.py --models")


# ── Step 5: Verify Pipeline ──────────────────────────────────────────────

def verify_pipeline():
    step("Verifying Trinity V8.2 Pipeline", "Testing all module imports...")

    venv_py = str(VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") /
                  ("python.exe" if IS_WINDOWS else "python3"))

    verify_script = """
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
    print(f'{failed} modules failed to import')
    sys.exit(1)
print(f'All {len(modules)} modules loaded successfully.')
"""

    try:
        result = run(
            [venv_py, "-c", verify_script],
            capture_output=False,
            cwd=str(ENGINE_DIR),
            check=False,
        )
        if result and result.returncode == 0:
            ok("All pipeline modules verified")
        else:
            warn("Some modules failed to import (models may not be downloaded yet)")
    except Exception:
        warn("Pipeline verification skipped")


# ── Step 6: Build Sidecar Binary ─────────────────────────────────────────

def build_sidecar():
    step("Building Trinity V8.2 Sidecar Binary", "PyInstaller → single executable...")

    venv_pip = str(PIP)
    venv_py = str(VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") /
                  ("python.exe" if IS_WINDOWS else "python3"))

    # Install PyInstaller
    pip_install("pyinstaller")
    ok("PyInstaller installed")

    spec_file = INSTALL_DIR / "trinity_v8_core.spec"
    if not spec_file.exists():
        warn(f"PyInstaller spec not found ({spec_file}). Skipping sidecar build.")
        warn("The sidecar binary must be built separately.")
        return

    # Ensure critical build deps
    pip_install("setuptools==69.5.1", "numpy<2.0")

    print("    Building sidecar (this may take 5-10 minutes)...")
    try:
        result = run(
            [venv_py, "-m", "PyInstaller", str(spec_file), "--noconfirm"],
            capture_output=False,
            cwd=str(INSTALL_DIR),
            check=False,
        )

        if result and result.returncode != 0:
            warn("Sidecar build had issues. Check output above.")
            return

        # Copy to Tauri binaries dir
        triple = TARGET_TRIPLE.get((platform.system(), ARCH))
        if not triple:
            warn(f"Unknown target triple for {platform.system()}/{ARCH}")
            return

        src_name = "trinity_v8_core.exe" if IS_WINDOWS else "trinity_v8_core"
        src = INSTALL_DIR / "dist" / ("trinity_v8_core" if not IS_WINDOWS else "trinity_v8_core.exe")

        # PyInstaller may output to dist/trinity_v8_core/ (onedir) or dist/trinity_v8_core (onefile)
        if not src.exists():
            src = INSTALL_DIR / "dist" / "trinity_v8_core" / src_name
        if not src.exists():
            warn(f"Built binary not found at expected path. Check dist/ directory.")
            return

        dest_name = f"trinity_v8_core-{triple}" + (".exe" if IS_WINDOWS else "")
        dest_dir = APP_DIR / "src-tauri" / "binaries"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / dest_name

        shutil.copy2(str(src), str(dest))
        size_mb = dest.stat().st_size / (1024 * 1024)
        ok(f"Sidecar binary: {dest} ({size_mb:.0f} MB)")

    except Exception as e:
        warn(f"Sidecar build failed: {e}")
        warn("You can rebuild later: pyinstaller trinity_v8_core.spec --noconfirm")


# ── Step 7: Frontend Dependencies ─────────────────────────────────────────

def install_frontend():
    step("Installing Frontend Dependencies", "React + Tauri...")

    if not (APP_DIR / "package.json").exists():
        warn("app/package.json not found. Skipping frontend.")
        return

    if not shutil.which("npm"):
        warn("npm not found. Skipping frontend install.")
        return

    try:
        run(["npm", "install"], capture_output=False, cwd=str(APP_DIR), check=False)
        ok("Frontend dependencies installed")
    except Exception as e:
        warn(f"Frontend install failed: {e}")


# ── Launchers ─────────────────────────────────────────────────────────────

def create_launchers():
    if IS_MACOS or IS_LINUX:
        _create_unix_launchers()
    elif IS_WINDOWS:
        _create_windows_launchers()


def _create_unix_launchers():
    launcher = INSTALL_DIR / "VOXIS.command"
    launcher.write_text(f"""#!/bin/bash
# VOXIS 4.0 DENSE Launcher — Glass Stone LLC
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/venv/bin/activate"
export PYTORCH_ENABLE_MPS_FALLBACK=1

echo ">> [VOXIS] Starting Trinity V8.2 Engine..."
echo ">> [VOXIS] Platform: $(uname -s) $(uname -m)"

if command -v npm &>/dev/null && [ -f "$DIR/app/package.json" ]; then
    cd "$DIR/app"
    npm run tauri dev 2>&1
else
    echo ">> [VOXIS] Running in CLI mode."
    cd "$DIR/trinity_engine"
    exec bash
fi
""")
    launcher.chmod(0o755)

    cli = INSTALL_DIR / "voxis-cli.sh"
    cli.write_text(f"""#!/bin/bash
# VOXIS CLI — processes audio from the command line
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/venv/bin/activate"
export PYTORCH_ENABLE_MPS_FALLBACK=1
cd "$DIR/trinity_engine"
python3 trinity_core.py "$@"
""")
    cli.chmod(0o755)
    ok("Launchers: VOXIS.command, voxis-cli.sh")


def _create_windows_launchers():
    launcher = INSTALL_DIR / "VOXIS.bat"
    launcher.write_text(f"""@echo off
REM VOXIS 4.0 DENSE Launcher — Glass Stone LLC
setlocal
set "DIR=%~dp0"
call "%DIR%venv\\Scripts\\activate.bat"

echo >> [VOXIS] Starting Trinity V8.2 Engine...
echo >> [VOXIS] Platform: Windows {ARCH}

if exist "%DIR%app\\package.json" (
    if exist "%DIR%tools\\ffmpeg" set "PATH=%DIR%tools\\ffmpeg;%PATH%"
    cd /d "%DIR%app"
    npm run tauri dev
) else (
    echo >> [VOXIS] Running in CLI mode.
    cd /d "%DIR%trinity_engine"
    cmd /k
)
""")

    cli = INSTALL_DIR / "voxis-cli.bat"
    cli.write_text(f"""@echo off
REM VOXIS CLI — processes audio from the command line
setlocal
set "DIR=%~dp0"
call "%DIR%venv\\Scripts\\activate.bat"
if exist "%DIR%tools\\ffmpeg" set "PATH=%DIR%tools\\ffmpeg;%PATH%"
cd /d "%DIR%trinity_engine"
python trinity_core.py %*
""")
    ok("Launchers: VOXIS.bat, voxis-cli.bat")


# ── Check Installation ────────────────────────────────────────────────────

def check_installation():
    print(f"\n{BOLD('=== VOXIS Installation Status ===')}\n")

    checks = {
        "Python venv": VENV_DIR.exists(),
        "pip": PIP is not None and Path(str(PIP)).exists() if PIP else VENV_DIR.exists(),
        "FFmpeg": shutil.which("ffmpeg") is not None,
        "Node.js": shutil.which("node") is not None,
    }

    # Check sidecar
    triple = TARGET_TRIPLE.get((platform.system(), ARCH), "unknown")
    ext = ".exe" if IS_WINDOWS else ""
    sidecar = APP_DIR / "src-tauri" / "binaries" / f"trinity_v8_core-{triple}{ext}"
    checks["Sidecar binary"] = sidecar.exists()

    # Check models
    home = Path.home()
    models_dir = home / ".voxis" / "dependencies" / "models"
    dev_models = ENGINE_DIR / "dependencies" / "models"
    checks["Models directory"] = models_dir.exists() or dev_models.exists()

    for name, installed in checks.items():
        icon = GREEN("[OK]") if installed else RED("[  ]")
        print(f"  {icon} {name}")

    # Check model detail via registry
    try:
        sys.path.insert(0, str(ENGINE_DIR))
        from model_registry import check_all_models
        status = check_all_models()
        print(f"\n  Models: {status['total_size_mb']/1024:.1f} GB total, "
              f"{status['missing_size_mb']/1024:.1f} GB missing")
        for m in status["models"]:
            icon = GREEN("[OK]") if m["installed"] else RED("[  ]")
            print(f"    {icon} {m['name']} ({m['size_mb']} MB)")
    except Exception:
        pass

    print()


# ── Completion Banner ─────────────────────────────────────────────────────

def complete_banner():
    print()
    print(GREEN("╔══════════════════════════════════════════════════════════════╗"))
    print(GREEN("║") + "  " + BOLD("✓ VOXIS 4.0 DENSE — Installation Complete!") + "               " + GREEN("║"))
    print(GREEN("╚══════════════════════════════════════════════════════════════╝"))
    print()

    if IS_WINDOWS:
        print(f"  {BOLD('To launch:')}")
        print(f"    {CYAN('•')} Double-click {CYAN('VOXIS.bat')} (Desktop App)")
        print(f"    {CYAN('•')} Or from terminal:")
        print(f"      voxis-cli.bat --input audio.wav --output restored.wav")
    else:
        print(f"  {BOLD('To launch:')}")
        print(f"    {CYAN('•')} Double-click {CYAN('VOXIS.command')} (Desktop App)")
        print(f"    {CYAN('•')} Or from terminal:")
        print(f"      ./voxis-cli.sh --input audio.wav --output restored.wav")

    print()
    print(f"  {BOLD('Quick Test:')}")
    if IS_WINDOWS:
        print(f"    voxis-cli.bat --input <any_audio_file> --output output.wav")
    else:
        print(f"    ./voxis-cli.sh --input <any_audio_file> --output output.wav")
    print()
    print(f"  © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez")
    print()


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VOXIS V4.0.0 DENSE — Cross-Platform Installer"
    )
    parser.add_argument("--models", action="store_true",
                        help="Download ML models only")
    parser.add_argument("--deps", action="store_true",
                        help="Install Python dependencies only")
    parser.add_argument("--build", action="store_true",
                        help="Build sidecar binary only")
    parser.add_argument("--check", action="store_true",
                        help="Check installation status")
    parser.add_argument("--no-models", action="store_true",
                        help="Skip model download")
    parser.add_argument("--no-build", action="store_true",
                        help="Skip sidecar binary build")
    args = parser.parse_args()

    banner()

    # Partial modes
    if args.check:
        setup_venv()
        check_installation()
        return

    if args.models:
        setup_venv()
        download_models()
        return

    if args.deps:
        setup_venv()
        install_deps()
        return

    if args.build:
        setup_venv()
        build_sidecar()
        return

    # Full install
    global TOTAL_STEPS
    if args.no_models:
        TOTAL_STEPS -= 1
    if args.no_build:
        TOTAL_STEPS -= 1

    check_system()
    setup_venv()
    install_deps()

    if not args.no_models:
        download_models()

    verify_pipeline()

    if not args.no_build:
        build_sidecar()

    install_frontend()
    create_launchers()
    complete_banner()


if __name__ == "__main__":
    main()
