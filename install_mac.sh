#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  VOXIS 4.0 DENSE — macOS Installer
#  Copyright © 2026 Glass Stone LLC. All Rights Reserved.
#  CEO: Gabriel B. Rodriguez
#  Powered by Trinity V8.2
# ═══════════════════════════════════════════════════════════════════
#
#  This installer:
#    1. Checks system requirements (macOS 12+, Python 3.10+, FFmpeg)
#    2. Creates a Python virtual environment
#    3. Installs all ML dependencies (torch, torchaudio, etc.)
#    4. Restores model weights from distro/ (~12 GB)
#    5. Builds the Trinity V8.2 sidecar binary
#    6. Creates a desktop launcher
#
#  Usage:
#    chmod +x install_mac.sh && ./install_mac.sh
# ═══════════════════════════════════════════════════════════════════

set -e

# ── Colors ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
ENGINE_DIR="$INSTALL_DIR/trinity_engine"
APP_DIR="$INSTALL_DIR/app"

banner() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}  ${BOLD}VOXIS 4.0 DENSE${NC} — Installer                          ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  Powered by Trinity V8.2                                ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez     ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

step() {
    echo -e "\n${BLUE}[$1/${TOTAL_STEPS}]${NC} ${BOLD}$2${NC}"
    echo -e "    ${YELLOW}$3${NC}"
}

ok() {
    echo -e "    ${GREEN}✓${NC} $1"
}

fail() {
    echo -e "    ${RED}✗ $1${NC}"
    echo -e "    ${RED}Installation aborted.${NC}"
    exit 1
}

warn() {
    echo -e "    ${YELLOW}⚠ $1${NC}"
}

TOTAL_STEPS=7

# ═══════════════════════════════════════════════════════════════════
banner

# ── Step 1: System Requirements ──────────────────────────────────
step 1 "Checking System Requirements" "macOS 12+, Python 3.10+, FFmpeg..."

# Check macOS version
MACOS_VER=$(sw_vers -productVersion 2>/dev/null || echo "0")
MACOS_MAJOR=$(echo "$MACOS_VER" | cut -d. -f1)
if [ "$MACOS_MAJOR" -lt 12 ] 2>/dev/null; then
    fail "macOS 12.0+ required (found $MACOS_VER)"
fi
ok "macOS $MACOS_VER"

# Check architecture
ARCH=$(uname -m)
ok "Architecture: $ARCH"

# Check Python
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        ok "Python $PY_VER"
    else
        fail "Python 3.10+ required (found $PY_VER). Install from python.org"
    fi
else
    fail "Python 3 not found. Install from https://www.python.org/downloads/"
fi

# Check FFmpeg
if command -v ffmpeg &>/dev/null; then
    FF_VER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
    ok "FFmpeg $FF_VER"
else
    warn "FFmpeg not found. Installing via Homebrew..."
    if command -v brew &>/dev/null; then
        brew install ffmpeg
        ok "FFmpeg installed via Homebrew"
    else
        fail "FFmpeg required. Install Homebrew first: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    fi
fi

# Check Node.js (for Tauri frontend build)
if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    ok "Node.js $NODE_VER"
else
    warn "Node.js not found. Frontend features may be limited."
fi

# Check available disk space (need ~15GB)
AVAIL_GB=$(df -g "$INSTALL_DIR" | tail -1 | awk '{print $4}')
if [ "$AVAIL_GB" -lt 15 ] 2>/dev/null; then
    warn "Low disk space: ${AVAIL_GB}GB available (15GB+ recommended)"
else
    ok "Disk space: ${AVAIL_GB}GB available"
fi

# Check RAM
RAM_GB=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1024/1024/1024}')
ok "RAM: ${RAM_GB}GB"

# ── Step 2: Python Virtual Environment ──────────────────────────
step 2 "Creating Python Virtual Environment" "$VENV_DIR"

if [ -d "$VENV_DIR" ]; then
    warn "Existing venv found. Reusing."
else
    python3 -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

source "$VENV_DIR/bin/activate"
ok "Activated venv ($(python3 --version))"

# Upgrade pip
pip install --upgrade pip --quiet
ok "pip upgraded"

# ── Step 3: Install Python Dependencies ─────────────────────────
step 3 "Installing ML Dependencies" "torch, torchaudio, audio-separator, deepfilternet, audiosr, voicerestore..."

# Pin torch/torchaudio/torchvision to avoid ABI breakage and TorchCodec issues
# (torchaudio 2.10+ requires torchcodec which is not widely available)
pip install torch==2.6.0 torchaudio==2.6.0 torchvision==0.21.0 --quiet

# Core audio tools
pip install pedalboard numpy soundfile librosa pyloudnorm --quiet

# Source separation
pip install "audio-separator[cpu]>=0.41.0" --quiet

# AudioSR neural super-resolution
pip install audiosr matplotlib --quiet

# VoiceRestore (Transformer-Diffusion) + all transitive deps
pip install huggingface_hub x-transformers gateloop-transformer jaxtyping torchdiffeq rotary-embedding-torch --quiet

# Apple Silicon Neural Engine acceleration (CoreML)
if [ "$ARCH" = "arm64" ]; then
    pip install coremltools>=9.0 "scikit-learn==1.5.1" --quiet
    ok "CoreML + scikit-learn installed (Neural Engine acceleration)"
fi

# ONNX cross-platform inference
pip install onnxruntime --quiet

# Telemetry & system
pip install requests psutil --quiet

# Install remaining dependencies from requirements.txt if present
if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    pip install -r "$INSTALL_DIR/requirements.txt" --quiet
    ok "All requirements.txt dependencies installed"
fi

ok "All dependencies installed"

# ── Step 4: Install & Download ML Models ──────────────────────
step 4 "Installing ML Models" "BS-RoFormer, VoiceRestore, AudioSR, BigVGAN, XLS-R, Diff-HierVC (~9.7 GB)..."

if [ -d "$ENGINE_DIR/distro/models" ]; then
    cd "$ENGINE_DIR"
    python3 setup_models.py
    ok "Models installed from distro/"
else
    echo ""
    echo -e "    ${BOLD}No local model cache found — downloading from HuggingFace...${NC}"
    echo -e "    ${YELLOW}This will download ~9.7 GB of ML models.${NC}"
    echo -e "    ${YELLOW}Models are cached at ~/.voxis/dependencies/models/${NC}"
    echo ""
    cd "$ENGINE_DIR"
    python3 model_downloader.py --download
    if [ $? -eq 0 ]; then
        ok "All models downloaded successfully"
    else
        warn "Some models may have failed. Retry with:"
        warn "  cd $ENGINE_DIR && python3 model_downloader.py --download"
    fi
fi

# Verify model status
cd "$ENGINE_DIR"
python3 model_registry.py 2>/dev/null || true

# ── Step 5: Verify Pipeline ─────────────────────────────────────
step 5 "Verifying Trinity V8.2 Pipeline" "Testing all module imports..."

cd "$ENGINE_DIR"
python3 -c "
import sys
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
print(f'  All {len(modules)} modules loaded successfully.')
" || fail "Module verification failed"
ok "All pipeline modules verified"

# ── Step 6: Build Frontend (if Node.js available) ───────────────
step 6 "Installing Frontend Dependencies" "React + Tauri..."

if command -v npm &>/dev/null && [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    npm install --silent 2>&1 | tail -2
    ok "Frontend dependencies installed"
else
    warn "Skipping frontend build (Node.js or app/ not found)"
fi

# ── Step 7: Create Launcher ─────────────────────────────────────
step 7 "Creating Desktop Launcher" "VOXIS.command..."

LAUNCHER="$INSTALL_DIR/VOXIS.command"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/bin/bash
# VOXIS 4.0 DENSE Launcher — Glass Stone LLC
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/venv/bin/activate"
export PYTORCH_ENABLE_MPS_FALLBACK=1

echo ">> [VOXIS] Starting Trinity V8.2 Engine..."
echo ">> [VOXIS] Platform: $(uname -s) $(uname -m)"

# Try Tauri desktop app first
if command -v npm &>/dev/null && [ -f "$DIR/app/package.json" ]; then
    cd "$DIR/app"
    npm run tauri dev 2>&1
else
    # Fallback: run engine CLI directly
    echo ">> [VOXIS] Running in CLI mode."
    echo ">> Usage: python3 trinity_core.py --input <file> --output <file>"
    cd "$DIR/trinity_engine"
    exec bash
fi
LAUNCHER_EOF
chmod +x "$LAUNCHER"
ok "Launcher created: $LAUNCHER"

# Also create a CLI shortcut
CLI_LAUNCHER="$INSTALL_DIR/voxis-cli.sh"
cat > "$CLI_LAUNCHER" << 'CLI_EOF'
#!/bin/bash
# VOXIS CLI — processes audio from the command line
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/venv/bin/activate"
export PYTORCH_ENABLE_MPS_FALLBACK=1
cd "$DIR/trinity_engine"
python3 trinity_core.py "$@"
CLI_EOF
chmod +x "$CLI_LAUNCHER"
ok "CLI launcher: $CLI_LAUNCHER"

# ═══════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}  ${BOLD}✓ VOXIS 4.0 DENSE — Installation Complete!${NC}            ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}To launch:${NC}"
echo -e "    ${CYAN}• Double-click${NC} VOXIS.command ${CYAN}(Desktop App)${NC}"
echo -e "    ${CYAN}• Or from terminal:${NC}"
echo -e "      ./voxis-cli.sh --input audio.wav --output restored.wav"
echo ""
echo -e "  ${BOLD}Quick Test:${NC}"
echo -e "    ./voxis-cli.sh --input <any_audio_file> --output output.wav"
echo ""
echo -e "  © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez"
echo ""
