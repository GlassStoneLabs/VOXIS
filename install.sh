#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  VOXIS 4.0 DENSE — Installer                                 ║
# ║  Copyright © 2026 Glass Stone LLC. All Rights Reserved.      ║
# ╚══════════════════════════════════════════════════════════════╝
#
# One-line install:
#   curl -fsSL https://raw.githubusercontent.com/GlassStoneLabs/VOXIS/main/install.sh | bash
#
# Installs: VOXIS app, FFmpeg (if missing), creates output folder.
# After install, launch VOXIS and enter your license key.

set -euo pipefail

APP_NAME="Voxis 4.0 DENSE"
APP_BUNDLE="Voxis 4.0 DENSE.app"
VERSION="4.0.0"
GITHUB_REPO="GlassStoneLabs/VOXIS"
DMG_NAME="Voxis.4.0.DENSE-${VERSION}-arm64.dmg"
DMG_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}/${DMG_NAME}"
DMG_FILE="/tmp/voxis-${VERSION}.dmg"
MOUNT_DIR="/Volumes/VOXIS 4.0 DENSE"
OUTPUT_DIR="$HOME/Music/Voxis Restored"

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}  ✓${RESET}  $*"; }
info() { echo -e "${CYAN}  →${RESET}  $*"; }
warn() { echo -e "${YELLOW}  ⚠${RESET}  $*"; }
die()  { echo -e "${RED}  ✗  ERROR:${RESET} $*" >&2; echo ""; exit 1; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║  VOXIS 4.0 DENSE  v${VERSION}                      ║${RESET}"
echo -e "${BOLD}  ║  Professional Voice Restoration              ║${RESET}"
echo -e "${BOLD}  ║  Glass Stone LLC © 2026                      ║${RESET}"
echo -e "${BOLD}  ╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ── System checks ─────────────────────────────────────────────────────────
info "Checking system requirements..."

# Architecture
ARCH=$(uname -m)
if [[ "$ARCH" != "arm64" ]]; then
  die "VOXIS requires Apple Silicon (arm64). Detected: $ARCH"
fi
ok "Architecture: arm64 (Apple Silicon)"

# macOS version
OS_VER=$(sw_vers -productVersion)
OS_MAJOR=$(echo "$OS_VER" | cut -d. -f1)
if [[ "$OS_MAJOR" -lt 12 ]]; then
  die "VOXIS requires macOS 12 Monterey or later. Detected: $OS_VER"
fi
ok "macOS $OS_VER"

# Disk space (need ~2GB free)
FREE_KB=$(df -k /Applications 2>/dev/null | awk 'NR==2 {print $4}')
FREE_GB=$(( FREE_KB / 1024 / 1024 ))
if [[ "$FREE_GB" -lt 2 ]]; then
  warn "Low disk space: ${FREE_GB}GB free (recommend 2GB+)"
fi

# ── FFmpeg check / install ────────────────────────────────────────────────
info "Checking FFmpeg..."
if command -v ffmpeg &>/dev/null; then
  FFMPEG_VER=$(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
  ok "FFmpeg $FFMPEG_VER ($(which ffmpeg))"
else
  warn "FFmpeg not found — required for audio decoding"
  if command -v brew &>/dev/null; then
    info "Installing FFmpeg via Homebrew..."
    brew install ffmpeg
    ok "FFmpeg installed"
  else
    echo ""
    echo -e "  ${YELLOW}Homebrew not found. Install FFmpeg manually:${RESET}"
    echo -e "  ${CYAN}  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"${RESET}"
    echo -e "  ${CYAN}  brew install ffmpeg${RESET}"
    echo ""
    die "FFmpeg is required. Install it and re-run this installer."
  fi
fi

# ── Remove old installations ─────────────────────────────────────────────
for old_app in \
  "/Applications/Voxis.app" \
  "/Applications/Voxis 4.0 DENSE.app" \
  "/Applications/${APP_BUNDLE}"
do
  if [[ -d "$old_app" ]]; then
    info "Removing existing installation: $old_app"
    rm -rf "$old_app"
    ok "Removed"
  fi
done

# ── Download DMG ─────────────────────────────────────────────────────────
info "Downloading VOXIS v${VERSION}..."
echo -e "  ${CYAN}Source: ${DMG_URL}${RESET}"
echo ""

if ! curl -fSL --progress-bar -o "$DMG_FILE" "$DMG_URL"; then
  die "Download failed. Check your internet connection or visit github.com/${GITHUB_REPO}/releases"
fi

DMG_SIZE=$(du -sh "$DMG_FILE" | cut -f1)
ok "Downloaded: $DMG_FILE ($DMG_SIZE)"

# ── Mount & install ───────────────────────────────────────────────────────
info "Mounting installer image..."
hdiutil attach "$DMG_FILE" -nobrowse -quiet

# Find the mounted app
MOUNTED_APP=""
for candidate in \
  "${MOUNT_DIR}/${APP_BUNDLE}" \
  "/Volumes/VOXIS/${APP_BUNDLE}" \
  "/Volumes/Voxis 4.0 DENSE/${APP_BUNDLE}"
do
  if [[ -d "$candidate" ]]; then
    MOUNTED_APP="$candidate"
    break
  fi
done

if [[ -z "$MOUNTED_APP" ]]; then
  # Search all volumes
  MOUNTED_APP=$(find /Volumes -maxdepth 2 -name "*.app" 2>/dev/null | grep -i voxis | head -1 || true)
fi

if [[ -z "$MOUNTED_APP" ]]; then
  hdiutil detach "$MOUNT_DIR" -quiet 2>/dev/null || true
  die "Could not find app bundle in DMG. Contents of /Volumes:\n$(ls /Volumes)"
fi

info "Installing to /Applications..."
cp -R "$MOUNTED_APP" "/Applications/${APP_BUNDLE}"
ok "Installed: /Applications/${APP_BUNDLE}"

# ── Unmount & cleanup ────────────────────────────────────────────────────
VOLUME_PATH=$(dirname "$MOUNTED_APP")
hdiutil detach "$VOLUME_PATH" -quiet 2>/dev/null || true
rm -f "$DMG_FILE"
ok "Cleanup complete"

# ── Remove Gatekeeper quarantine ─────────────────────────────────────────
info "Removing Gatekeeper quarantine..."
if xattr -r -d com.apple.quarantine "/Applications/${APP_BUNDLE}" 2>/dev/null; then
  ok "Quarantine removed"
else
  warn "Could not remove quarantine — you may see a security prompt on first launch"
  echo -e "  Run manually if needed: ${CYAN}xattr -r -d com.apple.quarantine \"/Applications/${APP_BUNDLE}\"${RESET}"
fi

# ── Create output directory ───────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"
ok "Output folder: $OUTPUT_DIR"

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}  ╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║  Installation Complete!                      ║${RESET}"
echo -e "${BOLD}  ╚══════════════════════════════════════════════╝${RESET}"
echo ""
ok "VOXIS ${VERSION} installed to /Applications/${APP_BUNDLE}"
ok "Output folder: ${OUTPUT_DIR}"
echo ""
echo -e "  ${BOLD}Next steps:${RESET}"
echo -e "  1. Launch VOXIS from Applications or run:"
echo -e "     ${CYAN}open '/Applications/${APP_BUNDLE}'${RESET}"
echo -e "  2. Enter your license key when prompted"
echo -e "  3. Purchase a license at: ${CYAN}https://voxis.glassstone.io${RESET}"
echo ""
echo -e "  ${BOLD}Quick launch:${RESET}"
echo -e "  ${CYAN}open '/Applications/${APP_BUNDLE}'${RESET}"
echo ""

# Auto-launch option
if [[ -t 0 ]]; then   # Only if running interactively
  read -r -p "  Launch VOXIS now? [y/N]: " LAUNCH
  if [[ "${LAUNCH,,}" == "y" ]]; then
    open "/Applications/${APP_BUNDLE}"
    ok "Launching VOXIS..."
  fi
fi
