#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  VOXIS V4.0.0 DENSE — Full Build Compiler                   ║
# ║  Copyright © 2026 Glass Stone LLC. All Rights Reserved.      ║
# ║  CEO: Gabriel B. Rodriguez                                   ║
# ╚══════════════════════════════════════════════════════════════╝
#
# Builds the complete VOXIS distribution:
#   1. Python engine → frozen binary via PyInstaller
#   2. Copies binary → app/resources/bin/
#   3. Electron app  → signed DMG installer
#
# Usage:
#   ./compile.sh                     full build (binary + DMG)
#   ./compile.sh --binary-only       Python binary only
#   ./compile.sh --app-only          Electron DMG only (binary must exist)
#   ./compile.sh --sign "Dev ID"     enable macOS code signing
#   ./compile.sh --clean             wipe dist/ and node_modules cache first

set -euo pipefail

# ── Colors ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET}  $*"; }
info() { echo -e "${CYAN}  →${RESET}  $*"; }
warn() { echo -e "${YELLOW}  ⚠${RESET}  $*"; }
die()  { echo -e "${RED}  ✗${RESET}  $*" >&2; exit 1; }
hr()   { echo -e "${BOLD}──────────────────────────────────────────────${RESET}"; }

# ── Config ─────────────────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT_DIR/app"
ENGINE_DIR="$ROOT_DIR/trinity_engine"
SPEC_FILE="$ROOT_DIR/trinity_v8_core.spec"
BINARY_NAME="trinity_v8_core"
BIN_SRC="$ROOT_DIR/dist/$BINARY_NAME"
BIN_DEST="$APP_DIR/resources/bin/$BINARY_NAME"
PYTHON_MIN="3.10"
NODE_MIN="18"

# ── Flags ──────────────────────────────────────────────────────────────────
DO_BINARY=true
DO_APP=true
SIGN_IDENTITY=""
CLEAN=false

for arg in "$@"; do
  case "$arg" in
    --binary-only) DO_APP=false ;;
    --app-only)    DO_BINARY=false ;;
    --clean)       CLEAN=true ;;
    --sign)        shift; SIGN_IDENTITY="${1:-}" ;;
    --sign=*)      SIGN_IDENTITY="${arg#--sign=}" ;;
    -h|--help)
      echo "Usage: $0 [--binary-only] [--app-only] [--sign 'Dev ID'] [--clean]"
      exit 0 ;;
  esac
done

# ── Banner ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║  VOXIS V4.0.0 DENSE — Build Compiler        ║${RESET}"
echo -e "${BOLD}  ║  Glass Stone LLC © 2026                      ║${RESET}"
echo -e "${BOLD}  ╚══════════════════════════════════════════════╝${RESET}"
echo ""
BUILD_START=$SECONDS

# ── Optional clean ─────────────────────────────────────────────────────────
if $CLEAN; then
  hr
  info "Cleaning previous build artifacts..."
  rm -rf "$ROOT_DIR/dist" "$ROOT_DIR/build" "$APP_DIR/dist" \
         "$APP_DIR/dist-electron" "$APP_DIR/release"
  ok "Clean complete"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PART 1: Python binary
# ═══════════════════════════════════════════════════════════════════════════
if $DO_BINARY; then
  hr
  echo -e "${BOLD}  STAGE 1 — Python Engine Compilation${RESET}"
  hr

  # ── Check Python ─────────────────────────────────────────────────────────
  info "Checking Python..."
  PYTHON=""
  for py in python3.11 python3.12 python3.10 python3 python; do
    if command -v "$py" &>/dev/null; then
      ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
      major="${ver%%.*}"; minor="${ver##*.}"
      if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
        PYTHON="$py"
        ok "Python $ver → $PYTHON"
        break
      fi
    fi
  done
  [[ -z "$PYTHON" ]] && die "Python $PYTHON_MIN+ required. Install via: brew install python@3.11"

  # ── Check pip ────────────────────────────────────────────────────────────
  info "Checking pip..."
  PIP="$PYTHON -m pip"
  $PIP --version &>/dev/null || die "pip not found. Run: $PYTHON -m ensurepip"
  ok "pip available"

  # ── Pin critical build deps ───────────────────────────────────────────────
  info "Pinning build-critical packages (setuptools, numpy)..."
  $PIP install -q "setuptools==69.5.1" "numpy<2.0" --upgrade
  ok "setuptools==69.5.1  numpy<2.0 pinned"

  # ── Install PyInstaller ───────────────────────────────────────────────────
  info "Checking PyInstaller..."
  if ! $PYTHON -c "import PyInstaller" &>/dev/null; then
    info "Installing PyInstaller..."
    $PIP install -q "pyinstaller>=6.0"
  fi
  PI_VER=$($PYTHON -c "import PyInstaller; print(PyInstaller.__version__)")
  ok "PyInstaller $PI_VER"

  # ── Install all runtime deps ──────────────────────────────────────────────
  info "Verifying runtime dependencies..."

  REQUIRED_PACKAGES=(
    "torch" "torchaudio" "soundfile" "librosa"
    "scipy" "numpy" "psutil" "requests" "certifi"
    "pedalboard" "transformers" "tokenizers"
    "huggingface_hub" "einops" "omegaconf" "filelock"
    "packaging" "onnxruntime"
  )

  MISSING=()
  for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if ! $PYTHON -c "import $pkg" &>/dev/null 2>&1; then
      MISSING+=("$pkg")
    fi
  done

  if [[ ${#MISSING[@]} -gt 0 ]]; then
    warn "Missing packages: ${MISSING[*]}"
    info "Installing missing packages..."
    $PIP install -q "${MISSING[@]}"
    ok "Dependencies installed"
  else
    ok "All runtime dependencies present"
  fi

  # Check optional but important
  for opt_pkg in "df" "audio_separator" "audiosr"; do
    if $PYTHON -c "import $opt_pkg" &>/dev/null 2>&1; then
      ok "$opt_pkg ✓"
    else
      warn "$opt_pkg not found — stage using it will fall back"
    fi
  done

  # ── Verify spec file ─────────────────────────────────────────────────────
  [[ -f "$SPEC_FILE" ]] || die "Spec file not found: $SPEC_FILE"
  ok "Spec: $(basename $SPEC_FILE)"

  # ── Run PyInstaller ──────────────────────────────────────────────────────
  hr
  info "Running PyInstaller (this takes 3-10 minutes)..."
  echo ""
  cd "$ROOT_DIR"

  PYINSTALLER_CMD="$PYTHON -m PyInstaller $SPEC_FILE --noconfirm --clean"
  if [[ -n "$SIGN_IDENTITY" ]]; then
    PYINSTALLER_CMD="$PYINSTALLER_CMD --codesign-identity '$SIGN_IDENTITY'"
  fi

  T0=$SECONDS
  eval $PYINSTALLER_CMD
  BINARY_TIME=$((SECONDS - T0))

  # ── Verify binary was produced ────────────────────────────────────────────
  [[ -f "$BIN_SRC" ]] || die "PyInstaller did not produce $BIN_SRC — check build output above"

  BIN_SIZE=$(du -sh "$BIN_SRC" | cut -f1)
  ok "Binary built: $BIN_SRC ($BIN_SIZE) in ${BINARY_TIME}s"

  # ── Copy binary to Electron resources ────────────────────────────────────
  info "Copying binary to app/resources/bin/..."
  mkdir -p "$(dirname "$BIN_DEST")"
  cp "$BIN_SRC" "$BIN_DEST"
  chmod +x "$BIN_DEST"
  DEST_SIZE=$(du -sh "$BIN_DEST" | cut -f1)
  ok "Binary deployed: $BIN_DEST ($DEST_SIZE)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# PART 2: Electron App
# ═══════════════════════════════════════════════════════════════════════════
if $DO_APP; then
  hr
  echo -e "${BOLD}  STAGE 2 — Electron App Build${RESET}"
  hr

  # ── Check binary exists ───────────────────────────────────────────────────
  if [[ ! -f "$BIN_DEST" ]]; then
    die "Binary not found at $BIN_DEST — run without --app-only first"
  fi
  ok "Binary: $(du -sh "$BIN_DEST" | cut -f1)"

  # ── Check Node.js ────────────────────────────────────────────────────────
  info "Checking Node.js..."
  command -v node &>/dev/null || die "Node.js not found. Install via: brew install node"
  NODE_VER=$(node -e "process.stdout.write(process.versions.node)")
  NODE_MAJOR="${NODE_VER%%.*}"
  [[ "$NODE_MAJOR" -ge "$NODE_MIN" ]] || die "Node.js $NODE_MIN+ required (found $NODE_VER)"
  ok "Node.js $NODE_VER"

  # ── Check npm ────────────────────────────────────────────────────────────
  command -v npm &>/dev/null || die "npm not found"
  ok "npm $(npm -v)"

  # ── Install npm dependencies ──────────────────────────────────────────────
  cd "$APP_DIR"
  info "Installing npm dependencies..."
  npm install --silent
  ok "npm dependencies installed"

  # ── Build Electron app ───────────────────────────────────────────────────
  info "Building Electron DMG (arm64)..."
  echo ""
  T0=$SECONDS

  if [[ -n "$SIGN_IDENTITY" ]]; then
    CSC_NAME="$SIGN_IDENTITY" npm run electron:build:mac 2>&1
  else
    # Disable code signing for unsigned builds
    CSC_IDENTITY_AUTO_DISCOVERY=false npm run electron:build:mac 2>&1
  fi

  APP_TIME=$((SECONDS - T0))

  # ── Find and report DMG ──────────────────────────────────────────────────
  DMG_PATH=$(find "$APP_DIR/release" -name "*.dmg" 2>/dev/null | head -1)
  if [[ -n "$DMG_PATH" ]]; then
    DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
    ok "DMG: $DMG_PATH ($DMG_SIZE) in ${APP_TIME}s"
  else
    warn "No DMG found in $APP_DIR/release — check electron-builder output"
  fi
fi

# ═══════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════
hr
TOTAL=$((SECONDS - BUILD_START))
MINS=$((TOTAL / 60)); SECS=$((TOTAL % 60))
echo ""
echo -e "${BOLD}  Build Complete in ${MINS}m ${SECS}s${RESET}"
echo ""

if $DO_BINARY && [[ -f "$BIN_DEST" ]]; then
  echo -e "  ${GREEN}●${RESET}  Binary   $(du -sh "$BIN_DEST" | cut -f1)   $BIN_DEST"
fi
if $DO_APP; then
  DMG_PATH=$(find "$APP_DIR/release" -name "*.dmg" 2>/dev/null | head -1 || true)
  if [[ -n "$DMG_PATH" ]]; then
    echo -e "  ${GREEN}●${RESET}  DMG      $(du -sh "$DMG_PATH" | cut -f1)       $DMG_PATH"
  fi
fi
echo ""
echo -e "  Distribute the DMG or run:"
echo -e "  ${CYAN}  open \"$APP_DIR/release/\"${RESET}"
echo ""
