#!/usr/bin/env python3
"""
VOXIS V4.0.0 DENSE — First-Run Setup
Copyright © 2026 Glass Stone LLC.

Restores models from the distro/ folder into the correct locations
so the Trinity V8.1 engine can run immediately after download.

Usage:
    python3 setup_models.py          # Install models from distro/
    python3 setup_models.py --check  # Verify installation
"""

import os
import sys
import shutil
import platform

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DISTRO_DIR = os.path.join(BASE_DIR, "distro", "models")
DEPS_DIR = os.path.join(BASE_DIR, "dependencies", "models")


def setup():
    """Install all models from distro/ into their expected locations."""
    print("\n=== VOXIS V4.0.0 DENSE — Model Setup ===")
    print(f"    Platform: {platform.system()} {platform.machine()}")
    print(f"    Source:   {DISTRO_DIR}")
    print()

    if not os.path.isdir(DISTRO_DIR):
        print("[ERROR] distro/models/ folder not found.")
        print("        Download the models package first.")
        sys.exit(1)

    # ── 1. GS-PRISM (Voice Isolation — BS-RoFormer backbone) ──────────────
    src = os.path.join(DISTRO_DIR, "audio_separator")
    dst = os.path.join(DEPS_DIR, "audio_separator")
    if os.path.isdir(src):
        _install(src, dst, "GS-PRISM")
    else:
        print("[SKIP] audio_separator not in distro/")

    # ── 2. GS-FORGE (Neural Noise Reduction — DeepFilterNet3 backbone) ───
    src = os.path.join(DISTRO_DIR, "deepfilternet")
    if platform.system() == "Darwin":
        dst = os.path.expanduser("~/Library/Caches/DeepFilterNet")
    else:
        dst = os.path.expanduser("~/.cache/DeepFilterNet")
    if os.path.isdir(src):
        _install(src, dst, "GS-FORGE")
    else:
        print("[SKIP] deepfilternet not in distro/")

    # ── 3. GS-CRYSTAL (Neural Restoration — VoiceRestore backbone) ───────
    src = os.path.join(DISTRO_DIR, "voicerestore")
    dst = os.path.join(DEPS_DIR, "voicerestore")
    if os.path.isdir(src):
        _install(src, dst, "GS-CRYSTAL")
    else:
        print("[SKIP] voicerestore not in distro/")

    # ── 4. GS-ASCEND (Audio Super-Resolution — AudioSR backbone) ─────────
    src = os.path.join(DISTRO_DIR, "audiosr")
    dst = os.path.join(DEPS_DIR, "huggingface")
    if os.path.isdir(src):
        _install(src, dst, "GS-ASCEND")
    else:
        print("[SKIP] audiosr not in distro/")

    print("\n=== Setup Complete ===")
    print("Run: python3 trinity_core.py --input <file> --output <file>\n")


def check():
    """Verify that all models are installed in the correct locations."""
    print("\n=== VOXIS Model Installation Check ===\n")
    all_ok = True

    checks = [
        ("GS-PRISM", os.path.join(DEPS_DIR, "audio_separator")),
        ("GS-FORGE",
         os.path.expanduser("~/Library/Caches/DeepFilterNet")
         if platform.system() == "Darwin"
         else os.path.expanduser("~/.cache/DeepFilterNet")),
        ("GS-CRYSTAL", os.path.join(DEPS_DIR, "voicerestore")),
        ("GS-ASCEND", os.path.join(DEPS_DIR, "huggingface")),
    ]

    for name, path in checks:
        found = _has_files(path)
        icon = "✓" if found else "✗"
        print(f"  [{icon}] {name:30} → {path}")
        if not found:
            all_ok = False

    print()
    if all_ok:
        print("✓ All models installed. Ready to run.\n")
    else:
        print("⚠ Some models missing. Run: python3 setup_models.py\n")
    return all_ok


def _install(src, dst, name):
    """Copy model directory, preserving existing files."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        # Merge instead of overwrite
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isdir(s):
                if os.path.exists(d):
                    shutil.rmtree(d)
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
    else:
        shutil.copytree(src, dst)

    size = _dir_size(dst)
    print(f"  [✓] {name} installed ({size}) → {dst}")


def _has_files(path):
    if not os.path.isdir(path):
        return False
    for root, dirs, files in os.walk(path):
        if files:
            return True
    return False


def _dir_size(path):
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    if total > 1024 ** 3:
        return f"{total / 1024**3:.1f} GB"
    elif total > 1024 ** 2:
        return f"{total / 1024**2:.0f} MB"
    return f"{total / 1024:.0f} KB"


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    else:
        setup()
        check()
