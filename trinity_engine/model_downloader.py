#!/usr/bin/env python3
"""
VOXIS V4.0.0 DENSE — First-Run Model Downloader
Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez

This script ships with the installer. On first launch, if the
`dependencies/models/` folder is empty, it downloads a zip archive
of pre-packaged ML weights from the Glass Stone CDN and extracts
them locally. This keeps the installer lightweight (~300 MB) while
providing a seamless one-click setup for the ~5 GB model payload.

Supported on both macOS and Windows.
"""

import os
import sys
import platform
import zipfile
import hashlib
import shutil
import time

# ── Configuration ───────────────────────────────────────────────────────────

# The Google Drive folder where Glass Stone hosts the model dependencies.
# Users will be directed here to download and unzip the model weights.
MODEL_PACK_URL = "https://drive.google.com/drive/folders/1aOCz4ElOn6vS007eRpkm0TfiVeyAUn_o?usp=share_link"
MODEL_PACK_SHA256 = None  # Set after first upload for integrity verification

# ── Resolve Paths (cross-platform) ──────────────────────────────────────────

def get_base_dir():
    """Returns the trinity_engine base dir, works inside PyInstaller bundles too."""
    if getattr(sys, 'frozen', False):
        # Running as compiled binary
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
MODELS_DIR = os.path.join(BASE_DIR, "dependencies", "models")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "dependencies", "downloads")


def models_exist() -> bool:
    """Check if the models directory has any content (not just empty dirs)."""
    if not os.path.isdir(MODELS_DIR):
        return False
    for root, dirs, files in os.walk(MODELS_DIR):
        if files:
            return True
    return False


def download_with_progress(url: str, dest_path: str):
    """Download a file with a simple progress indicator. Works on macOS + Windows."""
    import urllib.request

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    print(f"[Downloader] Fetching: {url}")
    print(f"[Downloader] Saving to: {dest_path}")

    def _progress(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 / total_size)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            sys.stdout.write(f"\r[Downloader] [{bar}] {pct:.1f}%  ({mb_done:.1f}/{mb_total:.1f} MB)")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest_path, reporthook=_progress)
    print()  # newline after progress bar


def verify_sha256(file_path: str, expected_hash: str) -> bool:
    """Verify file integrity via SHA-256."""
    if not expected_hash:
        print("[Downloader] No SHA-256 hash provided — skipping verification.")
        return True

    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    actual = sha.hexdigest()
    if actual != expected_hash:
        print(f"[Downloader] ✗ SHA-256 mismatch!")
        print(f"  Expected: {expected_hash}")
        print(f"  Got:      {actual}")
        return False
    print(f"[Downloader] ✓ SHA-256 verified: {actual[:16]}...")
    return True


def extract_zip(zip_path: str, dest_dir: str):
    """Extract a zip archive to the destination directory."""
    print(f"[Downloader] Extracting to: {dest_dir}")
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        total = len(zf.namelist())
        for i, name in enumerate(zf.namelist()):
            zf.extract(name, dest_dir)
            if (i + 1) % 50 == 0 or (i + 1) == total:
                pct = (i + 1) * 100 / total
                sys.stdout.write(f"\r[Downloader] Extracting... {pct:.0f}% ({i+1}/{total})")
                sys.stdout.flush()
    print()
    print(f"[Downloader] ✓ Extraction complete ({total} files)")


def cleanup_download(zip_path: str):
    """Remove the downloaded zip to save disk space."""
    try:
        os.remove(zip_path)
        print(f"[Downloader] Cleaned up: {os.path.basename(zip_path)}")
    except OSError:
        pass


def run():
    """Main entry point — called on first launch."""
    print("=" * 60)
    print("  VOXIS V4.0.0 DENSE — Model Setup")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print("  Glass Stone LLC © 2026")
    print("=" * 60)

    if models_exist():
        print("[Downloader] Models already installed. Skipping download.")
        return True

    print("\n[Downloader] First-run detected — GS model weights not found.")
    print("[Downloader] Downloading Trinity V8.1 model pack (GS-PRISM, GS-CRYSTAL, GS-ASCEND)...\n")

    zip_path = os.path.join(DOWNLOAD_DIR, "trinity_models_v8.1.zip")

    try:
        # Google Drive folders can't be directly downloaded via urllib.
        # Instead, we open the link in the user's browser for manual download.
        import webbrowser
        print("[Downloader] Opening Google Drive in your browser...")
        print(f"[Downloader] URL: {MODEL_PACK_URL}")
        webbrowser.open(MODEL_PACK_URL)
        
        print("\n" + "=" * 60)
        print("  INSTRUCTIONS:")
        print("  1. Download the model files from the Google Drive folder")
        print("  2. Unzip / extract the contents")
        print(f"  3. Place the model folders into:")
        print(f"     {MODELS_DIR}")
        print("  4. Restart VOXIS")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n[Downloader] ✗ Download failed: {e}")
        print("[Downloader] You can manually download the models from:")
        print(f"  {MODEL_PACK_URL}")
        print(f"  Extract to: {MODELS_DIR}")
        return False


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
