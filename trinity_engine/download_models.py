#!/usr/bin/env python3
"""
VOXIS V4.0.0 DENSE — Model Download & Distribution Setup
Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez

Downloads all required ML models and organizes them into the distro/ folder
for distribution. Others can download and run without additional setup.

Usage:
    python3 download_models.py              # Download all models
    python3 download_models.py --check      # Check which models are present
    python3 download_models.py --distro     # Copy models to distro/ folder

Models:
    1. BS-RoFormer (audio-separator) — Vocal isolation (~639 MB)
    2. DeepFilterNet3               — Neural denoising (~28 MB)
    3. AudioSR (basic)              — Audio super-resolution (~350 MB)
"""

import os
import sys
import shutil
import argparse

# Set MPS fallback before any torch import
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DISTRO_DIR = os.path.join(BASE_DIR, "distro", "models")
DEPS_DIR = os.path.join(BASE_DIR, "dependencies", "models")


# ── Model Definitions ────────────────────────────────────────────────────────

MODELS = {
    "audio_separator": {
        "name": "BS-RoFormer (Vocal Isolation)",
        "size": "~639 MB",
        "description": "Source separation model for isolating vocals from instruments.",
        "distro_subdir": "audio_separator",
    },
    "deepfilternet": {
        "name": "DeepFilterNet3 (Neural Denoising)",
        "size": "~28 MB",
        "description": "Real-time speech enhancement and noise suppression.",
        "distro_subdir": "deepfilternet",
    },
    "audiosr": {
        "name": "AudioSR Basic (Super Resolution)",
        "size": "~350 MB",
        "description": "Latent diffusion model for audio bandwidth extension to 48kHz.",
        "distro_subdir": "audiosr",
    },
}


def download_voice_restore():
    """Downloads the VoiceRestore weights via HuggingFace"""
    print("─" * 50)
    print("[3/4] Downloading VoiceRestore (Transformer-Diffusion)...")
    print("─" * 50)
    try:
        from huggingface_hub import hf_hub_download
        
        target_dir = os.path.join(DEPS_DIR, "voicerestore")
        os.makedirs(target_dir, exist_ok=True)
        
        print("Downloading VoiceRestore checkpoint (voicerestore-1.1.pth)...")
        cache_path = hf_hub_download(
            repo_id="jadechoghari/VoiceRestore", 
            filename="pytorch_model.bin",
            cache_dir=target_dir
        )
        print(f"[OK] VoiceRestore downloaded: {cache_path}")
        return True
    except Exception as e:
        print(f"✗ VoiceRestore download failed: {e}")
        return False


def check_models():
    """Check which models are already downloaded."""
    print("\n=== VOXIS Model Status ===\n")
    all_present = True

    # Check audio-separator model
    sep_dir = os.path.join(DEPS_DIR, "audio_separator")
    sep_distro = os.path.join(DISTRO_DIR, "audio_separator")
    sep_found = _dir_has_files(sep_dir) or _dir_has_files(sep_distro)
    _print_status("audio_separator", "BS-RoFormer", sep_found, sep_dir)
    if not sep_found:
        all_present = False

    # Check DeepFilterNet model (uses OS-specific cache)
    df_paths = [
        os.path.expanduser("~/Library/Caches/DeepFilterNet"),  # macOS
        os.path.expanduser("~/.cache/DeepFilterNet"),          # Linux
    ]
    df_distro = os.path.join(DISTRO_DIR, "deepfilternet")
    df_found = _dir_has_files(df_distro)
    df_src = df_distro
    for p in df_paths:
        if _dir_has_files(p):
            df_found = True
            df_src = p
            break
    _print_status("deepfilternet", "DeepFilterNet3", df_found, df_src)
    if not df_found:
        all_present = False

    # Check VoiceRestore model
    vr_dir = os.path.join(DEPS_DIR, "voicerestore")
    vr_distro = os.path.join(DISTRO_DIR, "voicerestore")
    vr_found = _dir_has_files(vr_dir) or _dir_has_files(vr_distro)
    _print_status("voicerestore", "VoiceRestore", vr_found, vr_dir)
    if not vr_found:
        all_present = False

    # Check AudioSR model
    hf_cache = os.path.join(DEPS_DIR, "huggingface")
    asr_distro = os.path.join(DISTRO_DIR, "audiosr")
    asr_found = _dir_has_files(hf_cache) or _dir_has_files(asr_distro)
    _print_status("audiosr", "AudioSR Basic", asr_found, hf_cache)
    if not asr_found:
        all_present = False

    print()
    if all_present:
        print("[OK] All models present.")
    else:
        print("[!] Some models missing. Run: python3 download_models.py")
    print()
    return all_present


def download_all():
    """Download all models by importing and initializing each module."""
    print("\n=== Downloading All VOXIS Models ===\n")

    # ── 1. BS-Roformer (audio-separator) ─────────────────────────────────
    print("─" * 50)
    print("[1/4] Downloading BS-RoFormer (audio-separator)...")
    print("─" * 50)
    try:
        import logging
        from audio_separator.separator import Separator
        sep_model_dir = os.path.join(DEPS_DIR, "audio_separator")
        os.makedirs(sep_model_dir, exist_ok=True)
        sep = Separator(
            log_level=logging.WARNING,
            model_file_dir=sep_model_dir,
            output_dir=os.path.join(BASE_DIR, "trinity_temp"),
        )
        sep.load_model(model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt")
        print("[[OK]] BS-RoFormer downloaded and verified.\n")
    except Exception as e:
        print(f"[✗] BS-RoFormer download failed: {e}\n")

    # ── 2. DeepFilterNet3 ────────────────────────────────────────────────
    print("─" * 50)
    print("[2/4] Downloading DeepFilterNet3...")
    print("─" * 50)
    try:
        from df.enhance import init_df
        model, df_state, _ = init_df()
        print(f"[[OK]] DeepFilterNet3 downloaded (sample rate: {df_state.sr()}Hz).\n")
        del model, df_state
    except Exception as e:
        print(f"[✗] DeepFilterNet3 download failed: {e}\n")

    # ── 3. VoiceRestore ──────────────────────────────────────────────────
    print("─" * 50)
    print("[3/4] Downloading VoiceRestore (Transformer-Diffusion)...")
    print("─" * 50)
    try:
        download_voice_restore()
        print("[[OK]] VoiceRestore downloaded and verified.\n")
    except Exception as e:
        print(f"[✗] VoiceRestore download failed: {e}\n")

    # ── 4. AudioSR ──────────────────────────────────────────────────────
    print("─" * 50)
    print("[4/4] Downloading AudioSR (basic model)...")
    print("─" * 50)
    try:
        hf_cache = os.path.join(DEPS_DIR, "huggingface")
        os.makedirs(hf_cache, exist_ok=True)
        os.environ["HUGGINGFACE_HUB_CACHE"] = hf_cache
        os.environ["AUDIOSR_CACHE_DIR"] = hf_cache

        from audiosr import build_model
        audiosr_model = build_model(model_name="basic", device="cpu")
        print(f"[[OK]] AudioSR downloaded and verified.\n")
        del audiosr_model
    except Exception as e:
        print(f"[✗] AudioSR download failed: {e}\n")

    import gc
    gc.collect()
    print("=== All downloads complete ===\n")


def copy_to_distro():
    """Copy all downloaded models into the distro/ folder for distribution."""
    print("\n=== Copying Models to distro/ ===\n")
    os.makedirs(DISTRO_DIR, exist_ok=True)

    # ── 1. audio-separator ───────────────────────────────────────────────
    src = os.path.join(DEPS_DIR, "audio_separator")
    dst = os.path.join(DISTRO_DIR, "audio_separator")
    if _dir_has_files(src):
        _mirror_dir(src, dst)
        print(f"[[OK]] audio_separator → distro/ ({_dir_size(dst)})")
    else:
        print("[SKIP] audio_separator not found in dependencies/")

    # ── 2. DeepFilterNet (from OS-specific cache) ─────────────────────────
    df_paths = [
        os.path.expanduser("~/Library/Caches/DeepFilterNet"),  # macOS
        os.path.expanduser("~/.cache/DeepFilterNet"),          # Linux
    ]
    dst = os.path.join(DISTRO_DIR, "deepfilternet")
    df_found = False
    for df_src in df_paths:
        if _dir_has_files(df_src):
            _mirror_dir(df_src, dst)
            print(f"[[OK]] deepfilternet → distro/ ({_dir_size(dst)})")
            df_found = True
            break
    if not df_found:
        print("[SKIP] DeepFilterNet not found in system cache")

    # ── 3. VoiceRestore ──────────────────────────────────────────────────
    vr_src = os.path.join(DEPS_DIR, "voicerestore")
    vr_dst = os.path.join(DISTRO_DIR, "voicerestore")
    if _dir_has_files(vr_src):
        _mirror_dir(vr_src, vr_dst)
        print(f"[[OK]] voicerestore → distro/ ({_dir_size(vr_dst)})")
    else:
        print("[SKIP] VoiceRestore not found in dependencies/")

    # ── 4. AudioSR (from HuggingFace cache) ──────────────────────────────
    hf_src = os.path.join(DEPS_DIR, "huggingface")
    dst = os.path.join(DISTRO_DIR, "audiosr")
    if _dir_has_files(hf_src):
        _mirror_dir(hf_src, dst)
        print(f"[[OK]] audiosr → distro/ ({_dir_size(dst)})")
    else:
        print("[SKIP] AudioSR not found in dependencies/")

    print(f"\nTotal distro size: {_dir_size(DISTRO_DIR)}")
    print("=== Distribution folder ready ===\n")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _dir_has_files(path):
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
    else:
        return f"{total / 1024:.0f} KB"


def _mirror_dir(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _print_status(key, name, found, path):
    icon = "[OK]" if found else "✗"
    status = "FOUND" if found else "MISSING"
    print(f"  [{icon}] {name:40} {status:8} → {path}")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VOXIS Model Downloader")
    parser.add_argument("--check", action="store_true", help="Check model status only")
    parser.add_argument("--distro", action="store_true", help="Copy models to distro/")
    args = parser.parse_args()

    if args.check:
        check_models()
    elif args.distro:
        copy_to_distro()
    else:
        download_all()
        copy_to_distro()
        check_models()
