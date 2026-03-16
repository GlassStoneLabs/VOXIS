#!/bin/bash
# VOXIS 4.0 DENSE — One-line Installer
# Copyright (c) 2026 Glass Stone LLC. All Rights Reserved.
#
# Usage: curl -fsSL https://raw.githubusercontent.com/GlassStoneLabs/VOXIS/main/install.sh | bash

set -euo pipefail

APP_NAME="Voxis 4.0 DENSE"
VERSION="4.0.0"
DMG_URL="https://github.com/GlassStoneLabs/VOXIS/releases/download/v${VERSION}/Voxis.4.0.DENSE-${VERSION}-arm64.dmg"
DMG_FILE="/tmp/voxis-${VERSION}.dmg"
MOUNT_POINT="/Volumes/${APP_NAME}"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  VOXIS 4.0 DENSE — Glass Stone LLC      ║"
echo "  ║  Professional Audio Restoration          ║"
echo "  ║  Powered by Trinity V8.1                 ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# Check architecture
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "[ERROR] Voxis 4.0 DENSE requires Apple Silicon (arm64)."
    exit 1
fi

# Check macOS version
macos_ver=$(sw_vers -productVersion | cut -d. -f1)
if [[ "$macos_ver" -lt 12 ]]; then
    echo "[ERROR] Voxis requires macOS 12 (Monterey) or later."
    exit 1
fi

# Check FFmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "[WARNING] FFmpeg not found. Installing via Homebrew..."
    if command -v brew &>/dev/null; then
        brew install ffmpeg
    else
        echo "[ERROR] FFmpeg is required. Install it with: brew install ffmpeg"
        exit 1
    fi
fi

# Download DMG
echo ">> Downloading ${APP_NAME} v${VERSION}..."
curl -fSL --progress-bar -o "$DMG_FILE" "$DMG_URL"

# Mount DMG
echo ">> Mounting installer..."
hdiutil attach "$DMG_FILE" -nobrowse -quiet

# Copy to Applications
echo ">> Installing to /Applications..."
if [[ -d "/Applications/${APP_NAME}.app" ]]; then
    echo "   Removing previous version..."
    rm -rf "/Applications/${APP_NAME}.app"
fi
cp -R "${MOUNT_POINT}/${APP_NAME}.app" /Applications/

# Unmount and clean up
hdiutil detach "$MOUNT_POINT" -quiet
rm -f "$DMG_FILE"

# Create output directory
mkdir -p "$HOME/Music/Voxis Restored"

echo ""
echo "  ✓ ${APP_NAME} installed successfully!"
echo "  ✓ Output folder: ~/Music/Voxis Restored/"
echo ""
echo "  Launch from Applications or run:"
echo "    open '/Applications/${APP_NAME}.app'"
echo ""
