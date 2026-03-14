#!/usr/bin/env bash
# =============================================================================
# VOXIS V4.0.0 DENSE — Desktop Build Script
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
BIN_OUT="${APP_DIR}/resources/bin"

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
echo ""

# ── Preflight ─────────────────────────────────────────────────────────────────
log "Checking build prerequisites..."
command -v node    >/dev/null || err "Node.js not found"
command -v python3 >/dev/null || err "Python 3 not found"
command -v ffmpeg  >/dev/null || warn "ffmpeg not found — install via Homebrew: brew install ffmpeg"
ok "Prerequisites OK"

if $CLEAN; then
  log "Cleaning previous build artifacts..."
  rm -rf "${APP_DIR}/dist" "${APP_DIR}/dist-electron" "${APP_DIR}/release"
  rm -rf "${PROJECT_ROOT}/dist" "${PROJECT_ROOT}/build"
  ok "Cleaned"
fi

# ── STEP 1: Build Trinity Engine (PyInstaller) ────────────────────────────────
if ! $SKIP_PYTHON; then
  log "STEP 1/3 — Building Trinity V8.1 Engine (PyInstaller)..."
  cd "${PROJECT_ROOT}"

  # Install Python deps (pin setuptools + numpy for PyInstaller compatibility)
  python3 -m pip install --quiet --upgrade pip wheel
  python3 -m pip install --quiet "setuptools==69.5.1" "numpy<2.0"
  python3 -m pip install --quiet -r "${ENGINE_DIR}/requirements.txt"
  python3 -m pip install --quiet pyinstaller

  # Build frozen binary
  SPEC_FILE="${PROJECT_ROOT}/trinity_v8_core.spec"
  if [[ ! -f "$SPEC_FILE" ]]; then
    err "PyInstaller spec file not found: $SPEC_FILE"
  fi
  pyinstaller --noconfirm --clean "$SPEC_FILE"

  # Stage binary for Electron
  mkdir -p "${BIN_OUT}"
  cp "${PROJECT_ROOT}/dist/trinity_v8_core" "${BIN_OUT}/trinity_v8_core"
  chmod +x "${BIN_OUT}/trinity_v8_core"
  ok "Trinity Engine binary staged → ${BIN_OUT}/trinity_v8_core"
else
  warn "Skipping Python build (--skip-python). Ensure binary exists at:"
  warn "  ${BIN_OUT}/trinity_v8_core"
fi

# ── STEP 2: Build Electron Frontend ─────────────────────────────────────────
log "STEP 2/3 — Installing Node dependencies..."
cd "${APP_DIR}"
npm ci
ok "Dependencies installed"

log "STEP 2/3 — Building Electron app..."
npm run electron:build
ok "Electron build complete"

# ── STEP 3: Report Output ────────────────────────────────────────────────────
log "STEP 3/3 — Build complete!"
RELEASE_DIR="${APP_DIR}/release"
if [[ -d "$RELEASE_DIR" ]]; then
  echo ""
  echo "  Output files:"
  find "$RELEASE_DIR" -name "*.dmg" -o -name "*.exe" | while read -r f; do
    SIZE=$(du -sh "$f" | cut -f1)
    echo "    ${GREEN}✓${NC} $(basename "$f")  ($SIZE)"
  done
  echo ""
fi
echo "  COPYRIGHT © 2026 GLASS STONE LLC — ALL RIGHTS RESERVED"
echo ""
