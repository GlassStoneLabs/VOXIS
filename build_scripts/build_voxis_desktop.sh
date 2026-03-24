#!/usr/bin/env bash
# =============================================================================
# VOXIS V4.0.0 DENSE — Desktop Build Script (Tauri)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Targets:
#   Primary   : macOS M-Series (aarch64-apple-darwin) → .dmg
#   Secondary : Windows x86_64 → .exe (cross-compile or run on Windows)
#
# Usage:
#   ./build_scripts/build_voxis_desktop.sh [--clean] [--skip-python]
# =============================================================================
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${BOLD}${BLUE}>>>${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${PROJECT_ROOT}/app"
ENGINE_DIR="${PROJECT_ROOT}/trinity_engine"
TAURI_DIR="${APP_DIR}/src-tauri"
BIN_OUT="${TAURI_DIR}/binaries"

# Detect target triple for sidecar naming
ARCH="$(uname -m)"
OS="$(uname -s)"
case "${OS}-${ARCH}" in
  Darwin-arm64)   TARGET_TRIPLE="aarch64-apple-darwin" ;;
  Darwin-x86_64)  TARGET_TRIPLE="x86_64-apple-darwin" ;;
  Linux-x86_64)   TARGET_TRIPLE="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64)  TARGET_TRIPLE="aarch64-unknown-linux-gnu" ;;
  *)              TARGET_TRIPLE="${ARCH}-unknown-${OS,,}" ;;
esac

CLEAN=false; SKIP_PYTHON=false
for arg in "$@"; do
  case $arg in
    --clean)        CLEAN=true ;;
    --skip-python)  SKIP_PYTHON=true ;;
  esac
done

echo ""
echo "  ██╗   ██╗ ██████╗ ██╗  ██╗██╗███████╗"
echo "  ██║   ██║██╔═══██╗╚██╗██╔╝██║██╔════╝"
echo "  ██║   ██║██║   ██║ ╚███╔╝ ██║███████╗"
echo "  ╚██╗ ██╔╝██║   ██║ ██╔██╗ ██║╚════██║"
echo "   ╚████╔╝ ╚██████╔╝██╔╝ ██╗██║███████║"
echo "    ╚═══╝   ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝"
echo "  V4.0.0 DENSE | Glass Stone LLC © 2026"
echo "  CEO: Gabriel B. Rodriguez"
echo "  Build target: ${TARGET_TRIPLE}"
echo ""

# ── Preflight ─────────────────────────────────────────────────────────────────
log "Checking build prerequisites..."
command -v node    >/dev/null || err "Node.js not found"
command -v python3 >/dev/null || err "Python 3 not found"
command -v cargo   >/dev/null || err "Rust/Cargo not found — install via rustup"
command -v ffmpeg  >/dev/null || warn "ffmpeg not found — install via Homebrew: brew install ffmpeg"
ok "Prerequisites OK"

if $CLEAN; then
  log "Cleaning previous build artifacts..."
  rm -rf "${APP_DIR}/dist" "${TAURI_DIR}/target/release/bundle"
  rm -rf "${PROJECT_ROOT}/dist" "${PROJECT_ROOT}/build"
  ok "Cleaned"
fi

# ── STEP 1: Build Trinity Engine (PyInstaller) ────────────────────────────────
if ! $SKIP_PYTHON; then
  log "STEP 1/3 — Building Trinity V8.2 Engine (PyInstaller)..."
  cd "${PROJECT_ROOT}"

  # Install Python deps (pin setuptools + numpy for PyInstaller compatibility)
  python3 -m pip install --quiet --upgrade pip wheel
  python3 -m pip install --quiet "setuptools==69.5.1" "numpy<2.0"
  python3 -m pip install --quiet -r "${ENGINE_DIR}/requirements.txt"
  python3 -m pip install --quiet pyinstaller

  # ── Build PhaseLimiter native binary (pre-bundle) ──────────────────────────
  PHASELIMITER_BIN="${ENGINE_DIR}/modules/external/phase/bin/Release/phase_limiter"
  if [[ ! -f "$PHASELIMITER_BIN" ]]; then
    log "Building PhaseLimiter native binary (Apple Accelerate)..."
    PHASELIMITER_BUILD="${ENGINE_DIR}/modules/external/phase/build_macos_native.sh"
    if [[ -f "$PHASELIMITER_BUILD" ]]; then
      bash "$PHASELIMITER_BUILD"
      if [[ -f "$PHASELIMITER_BIN" ]]; then
        ok "PhaseLimiter binary built → $(du -sh "$PHASELIMITER_BIN" | cut -f1)"
      else
        warn "PhaseLimiter build completed but binary not found — Stage 7 will use Harman/Pedalboard fallback"
      fi
    else
      warn "PhaseLimiter build script not found — skipping"
    fi
  else
    ok "PhaseLimiter binary already exists → $(du -sh "$PHASELIMITER_BIN" | cut -f1)"
  fi

  # Build frozen binary
  SPEC_FILE="${PROJECT_ROOT}/trinity_v8_core.spec"
  if [[ ! -f "$SPEC_FILE" ]]; then
    err "PyInstaller spec file not found: $SPEC_FILE"
  fi
  pyinstaller --noconfirm --clean "$SPEC_FILE"

  # Stage binary for Tauri sidecar (must match target triple naming)
  mkdir -p "${BIN_OUT}"
  cp "${PROJECT_ROOT}/dist/trinity_v8_core" "${BIN_OUT}/trinity_v8_core-${TARGET_TRIPLE}"
  chmod +x "${BIN_OUT}/trinity_v8_core-${TARGET_TRIPLE}"
  ok "Trinity Engine sidecar staged → ${BIN_OUT}/trinity_v8_core-${TARGET_TRIPLE}"
else
  warn "Skipping Python build (--skip-python). Ensure sidecar exists at:"
  warn "  ${BIN_OUT}/trinity_v8_core-${TARGET_TRIPLE}"
fi

# ── STEP 2: Build Tauri Desktop App ──────────────────────────────────────────
log "STEP 2/3 — Installing Node dependencies..."
cd "${APP_DIR}"
npm ci
ok "Dependencies installed"

log "STEP 2/3 — Building Tauri app..."
npm run tauri:build
ok "Tauri build complete"

# ── STEP 3: Report Output ────────────────────────────────────────────────────
log "STEP 3/3 — Build complete!"
BUNDLE_DIR="${TAURI_DIR}/target/release/bundle"
if [[ -d "$BUNDLE_DIR" ]]; then
  echo ""
  echo "  Output files:"
  find "$BUNDLE_DIR" -name "*.dmg" -o -name "*.exe" -o -name "*.msi" -o -name "*.deb" -o -name "*.AppImage" 2>/dev/null | while read -r f; do
    SIZE=$(du -sh "$f" | cut -f1)
    echo "    ${GREEN}✓${NC} $(basename "$f")  ($SIZE)"
  done
  echo ""
fi
echo "  COPYRIGHT © 2026 GLASS STONE LLC — ALL RIGHTS RESERVED"
echo ""
