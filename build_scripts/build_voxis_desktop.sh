#!/usr/bin/env bash
# =============================================================================
# VOXIS V4.0.0 DENSE — Desktop Build Script
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Targets:
#   Primary   : macOS M-Series (aarch64-apple-darwin)
#   Secondary : Windows x86_64
#
# Usage:
#   ./build_scripts/build_voxis_desktop.sh [--clean] [--skip-deps] [--tauri-only]
# =============================================================================
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${BOLD}${BLUE}>>>${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Flags ────────────────────────────────────────────────────────────────────
CLEAN=false; SKIP_DEPS=false; TAURI_ONLY=false
for arg in "$@"; do
  case $arg in
    --clean)      CLEAN=true ;;
    --skip-deps)  SKIP_DEPS=true ;;
    --tauri-only) TAURI_ONLY=true ;;
  esac
done

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"
log "VOXIS V4.0.0 DENSE Build — Glass Stone LLC © 2026"
log "Project root: ${PROJECT_ROOT}"

# ── Platform detection ───────────────────────────────────────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
  PLATFORM="macos"
  ARCH=$(uname -m)
  TAURI_TARGET=$( [ "$ARCH" = "arm64" ] && echo "aarch64-apple-darwin" || echo "x86_64-apple-darwin" )
  BINARY_EXT=""
else
  PLATFORM="windows"
  TAURI_TARGET="x86_64-pc-windows-msvc"
  BINARY_EXT=".exe"
fi
log "Platform: ${PLATFORM} (${TAURI_TARGET})"

EXT_DIR="${PROJECT_ROOT}/trinity_engine/modules/external"
BIN_DIR="${PROJECT_ROOT}/app/src-tauri/binaries"
mkdir -p "${EXT_DIR}" "${BIN_DIR}"

# ── Clean ────────────────────────────────────────────────────────────────────
if $CLEAN; then
  log "Cleaning build artifacts..."
  rm -rf "${PROJECT_ROOT}/dist" "${PROJECT_ROOT}/build"
  ok "Clean done."
fi

# ── STEP 1: External repos ───────────────────────────────────────────────────
if ! $TAURI_ONLY; then
  log "STEP 1/4 — Cloning external components..."

  _clone() {
    local url=$1 dest=$2 name=$3
    if [ -d "${dest}/.git" ]; then
      warn "${name}: already present."
    else
      rm -rf "${dest}"
      git clone --depth 1 "${url}" "${dest}" 2>/dev/null && ok "Cloned ${name}" \
        || warn "${name}: clone failed — continuing without it."
    fi
  }

  _clone "https://github.com/hayeong0/Diff-HierVC"          "${EXT_DIR}/diff_hiervc"   "Diff-HierVC"
  _clone "https://github.com/skirdey/voicerestore"           "${EXT_DIR}/voicerestore"  "VoiceRestore"
  _clone "https://github.com/ORI-Muchim/AudioSR-Upsampling"  "${EXT_DIR}/audiosr"       "AudioSR-Upsampling"
  _clone "https://github.com/Rikorose/DeepFilterNet"         "${EXT_DIR}/dfn"           "DeepFilterNet"
  _clone "https://github.com/ZFTurbo/MSS_ONNX_TensorRT"      "${EXT_DIR}/mss_onnx"      "MSS_ONNX_TensorRT"
  _clone "https://github.com/carperbr/frame-transformer.git" "${EXT_DIR}/frame_transformer" "Frame-Transformer"
  _clone "https://github.com/ai-mastering/phaselimiter-gui.git" "${EXT_DIR}/phaselimiter_gui" "PhaseLimiter-GUI"

  # Rebrand: strip upstream readmes + licenses, apply Glass Stone brand
  log "Rebranding external components..."
  find "${EXT_DIR}" \( -name "README*" -o -name "LICENSE*" \) -delete 2>/dev/null || true
  mkdir -p "${EXT_DIR}/voxis_separator"
  cp "${PROJECT_ROOT}/LICENSE.md" "${EXT_DIR}/voxis_separator/LICENSE_VOXIS.md"
  ok "External components rebranded."
fi

# ── STEP 2: Python deps ──────────────────────────────────────────────────────
if ! $SKIP_DEPS && ! $TAURI_ONLY; then
  log "STEP 2/4 — Installing Python dependencies..."
  [ -d "${PROJECT_ROOT}/.venv" ] && source "${PROJECT_ROOT}/.venv/bin/activate" && log "Using .venv"
  python3 -m pip install --upgrade pip setuptools wheel
  python3 -m pip install -r "${PROJECT_ROOT}/trinity_engine/requirements.txt"
  python3 -m pip install audiosr==0.0.7 --no-deps
  ok "Python deps installed."
fi

# ── STEP 3: Compile Trinity V8 Engine ───────────────────────────────────────
if ! $TAURI_ONLY; then
  log "STEP 3/4 — Compiling Trinity V8 Engine (PyInstaller)..."
  cd "${PROJECT_ROOT}"
  pyinstaller --noconfirm --clean "${PROJECT_ROOT}/trinity_v8_core.spec"

  BUILT="${PROJECT_ROOT}/dist/trinity_v8_core${BINARY_EXT}"
  [ -f "$BUILT" ] || err "PyInstaller output missing: ${BUILT}"

  TARGET_BIN="${BIN_DIR}/trinity_v8_core-${TAURI_TARGET}${BINARY_EXT}"
  cp "$BUILT" "$TARGET_BIN"
  chmod +x "$TARGET_BIN"
  ok "Engine binary → ${TARGET_BIN}"
fi

# ── STEP 4: Build Tauri installer ────────────────────────────────────────────
log "STEP 4/4 — Building Bauhaus UI + Tauri installer..."
cd "${PROJECT_ROOT}/app"
npm install
npm run tauri build

BUNDLE="${PROJECT_ROOT}/app/src-tauri/target/release/bundle"
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║  VOXIS V4.0.0 DENSE — BUILD COMPLETE                ║${NC}"
echo -e "${BOLD}${GREEN}║  Glass Stone LLC © 2026 — CEO: Gabriel B. Rodriguez ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
[ "$PLATFORM" = "macos" ] && ls -1 "${BUNDLE}/dmg/" 2>/dev/null | sed 's/^/  /' || true
[ "$PLATFORM" = "windows" ] && ls -1 "${BUNDLE}/nsis/" 2>/dev/null | sed 's/^/  /' || true
