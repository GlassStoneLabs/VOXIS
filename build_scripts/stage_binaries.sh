#!/usr/bin/env bash
# =============================================================================
# VOXIS V4.0.0 DENSE — Binary Staging Script
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# PURPOSE:
#   Before tagging a release (e.g. v4.0.1), upload the pre-built platform
#   binaries to a companion "vX.Y.Z-binaries" pre-release on GitHub.
#   The release.yml CI workflow downloads them from there to build installers.
#
# PREREQUISITES:
#   - gh CLI authenticated: gh auth login
#   - macOS binary built:   ./build_scripts/build_voxis_desktop.sh
#   - Windows binary built: (on Windows) .\build_scripts\build_windows_binary.ps1
#   - FFmpeg Windows bins:  ffmpeg.exe + ffprobe.exe in app/resources/bin/
#
# USAGE:
#   VERSION=4.0.1 ./build_scripts/stage_binaries.sh
# =============================================================================
set -euo pipefail

VERSION="${VERSION:-}"
if [[ -z "$VERSION" ]]; then
  echo "ERROR: Set VERSION first, e.g.  VERSION=4.0.1 ./build_scripts/stage_binaries.sh"
  exit 1
fi

REPO="GlassStoneLabs/VOXIS"
BINARY_TAG="v${VERSION}-binaries"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="${ROOT}/app/resources/bin"

echo ""
echo "  Staging binaries for v${VERSION} → ${BINARY_TAG}"
echo ""

# ── Create (or recreate) the binaries pre-release ────────────────────────────
gh release delete "${BINARY_TAG}" --repo "${REPO}" --yes 2>/dev/null || true

gh release create "${BINARY_TAG}" \
  --repo "${REPO}" \
  --prerelease \
  --title "Binaries v${VERSION}" \
  --notes "Pre-built binaries for Voxis v${VERSION}. Used by release.yml CI workflow. Not a user-facing release."

# ── Upload macOS binary ───────────────────────────────────────────────────────
MAC_BIN="${BIN_DIR}/trinity_v8_core"
if [[ -f "${MAC_BIN}" ]]; then
  gh release upload "${BINARY_TAG}" "${MAC_BIN}" --repo "${REPO}"
  echo "  ✓ Uploaded macOS binary"
else
  echo "  ✗ macOS binary not found: ${MAC_BIN}"
  echo "    Build it first: ./build_scripts/build_voxis_desktop.sh"
fi

# ── Upload Windows binary + FFmpeg ───────────────────────────────────────────
WIN_BIN="${BIN_DIR}/trinity_v8_core.exe"
FFMPEG="${BIN_DIR}/ffmpeg.exe"
FFPROBE="${BIN_DIR}/ffprobe.exe"

if [[ -f "${WIN_BIN}" ]]; then
  gh release upload "${BINARY_TAG}" "${WIN_BIN}" --repo "${REPO}"
  echo "  ✓ Uploaded Windows binary"
else
  echo "  ✗ Windows binary not found: ${WIN_BIN}"
  echo "    Build it on Windows: .\\build_scripts\\build_windows_binary.ps1"
fi

if [[ -f "${FFMPEG}" && -f "${FFPROBE}" ]]; then
  gh release upload "${BINARY_TAG}" "${FFMPEG}" "${FFPROBE}" --repo "${REPO}"
  echo "  ✓ Uploaded FFmpeg Windows binaries"
else
  echo "  ✗ FFmpeg binaries not found in ${BIN_DIR}"
  echo "    Download from https://github.com/BtbN/FFmpeg-Builds/releases"
fi

echo ""
echo "  Binaries staged to: https://github.com/${REPO}/releases/tag/${BINARY_TAG}"
echo ""
echo "  Next steps:"
echo "    1. Verify all binaries uploaded above"
echo "    2. Tag the release:"
echo "       git tag v${VERSION} && git push origin v${VERSION}"
echo "    3. release.yml CI will build DMG + NSIS and publish the release"
echo ""
