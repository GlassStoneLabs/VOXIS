#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#  VOXIS 4.0 DENSE — Distribution Packager
#  Creates a distributable archive containing everything needed.
#
#  Usage:
#    ./build_distro.sh          # Build VOXIS-Installer.tar.gz
#    ./build_distro.sh --slim   # Without models (users download later)
# ═══════════════════════════════════════════════════════════════════

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
DISTRO_NAME="VOXIS-4.0-DENSE-Installer"
OUT_DIR="$ROOT/dist"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  VOXIS 4.0 DENSE — Distribution Packager            ║"
echo "║  © 2026 Glass Stone LLC                              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

SLIM=false
if [ "$1" = "--slim" ]; then
    SLIM=true
    DISTRO_NAME="VOXIS-4.0-DENSE-Installer-SLIM"
    echo "[MODE] Slim build (without models — users download on first run)"
else
    echo "[MODE] Full build (with models — ~12 GB)"
fi

# Create staging directory
STAGE="$OUT_DIR/$DISTRO_NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE"

echo ""
echo "[1/5] Copying Trinity Engine..."
rsync -a --exclude='__pycache__' \
         --exclude='*.pyc' \
         --exclude='trinity_temp' \
         --exclude='dependencies/stage_cache' \
         --exclude='dependencies/error_cache' \
         "$ROOT/trinity_engine/" "$STAGE/trinity_engine/"

# Run model downloader to ensure distro/ expects all models (audio_separator, deepfilternet, voicerestore, audiosr)
echo "→ Structuring model directories..."
python3 "$STAGE/trinity_engine/download_models.py" --distro

# Remove distro/models if slim
if [ "$SLIM" = true ]; then
    rm -rf "$STAGE/trinity_engine/distro/models"
    echo "  → Skipped models (slim mode)"
else
    echo "  → Including models from distro/ ($(du -sh "$STAGE/trinity_engine/distro" 2>/dev/null | awk '{print $1}'))"
fi

echo "[2/5] Copying Frontend App..."
rsync -a --exclude='node_modules' \
         --exclude='dist' \
         --exclude='target' \
         --exclude='.git' \
         "$ROOT/app/" "$STAGE/app/"

echo "[3/5] Copying Installer Scripts..."
cp "$ROOT/install_mac.sh" "$STAGE/"
cp "$ROOT/install_win.ps1" "$STAGE/"
chmod +x "$STAGE/install_mac.sh"

# Copy root README and LICENSE
[ -f "$ROOT/README.md" ] && cp "$ROOT/README.md" "$STAGE/"
[ -f "$ROOT/LICENSE.md" ] && cp "$ROOT/LICENSE.md" "$STAGE/"

echo "[4/5] Creating archive..."
cd "$OUT_DIR"

if [ "$SLIM" = true ]; then
    # Slim is small enough for .zip
    zip -rq "${DISTRO_NAME}.zip" "$DISTRO_NAME/"
    ARCHIVE="${DISTRO_NAME}.zip"
else
    # Full archive uses tar.gz for better compression on large files
    tar -czf "${DISTRO_NAME}.tar.gz" "$DISTRO_NAME/"
    ARCHIVE="${DISTRO_NAME}.tar.gz"
fi

ARCHIVE_SIZE=$(du -sh "$OUT_DIR/$ARCHIVE" | awk '{print $1}')

echo "[5/5] Cleaning up staging..."
rm -rf "$STAGE"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✓ Distribution archive created!                     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Archive: $OUT_DIR/$ARCHIVE"
echo "  Size:    $ARCHIVE_SIZE"
echo ""
echo "  For end users:"
echo "    1. Extract the archive"
echo "    2. macOS: chmod +x install_mac.sh && ./install_mac.sh"
echo "    3. Windows: Right-click install_win.ps1 → Run with PowerShell"
echo ""
