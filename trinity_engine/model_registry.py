#!/usr/bin/env python3
"""
VOXIS V4.0.0 DENSE — Model Registry
Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez

Central manifest of all ML models required by the Trinity V8.2 pipeline.
Each entry specifies: source, expected location, size, checksum, and
whether HuggingFace Hub or direct download is used.

Used by:
  - model_downloader.py  (download orchestration)
  - trinity_core.py      (pre-flight check before pipeline runs)
  - Tauri host           (check_models IPC command)
"""

import os
import sys
import platform

# ── Base directory (frozen binary → ~/.voxis/, dev → trinity_engine/) ─────

def get_models_base():
    """Canonical writable models directory."""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.expanduser("~"), ".voxis", "dependencies", "models")
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "dependencies", "models")


# ── Model Definitions ────────────────────────────────────────────────────────

MODELS = [
    # ── GS-PRISM (BS-RoFormer voice isolation) ─────────────────────────────
    {
        "id":          "gs_prism_bsroformer",
        "name":        "GS-PRISM (BS-RoFormer)",
        "stage":       "SEPARATE",
        "source":      "direct",
        "url":         "https://huggingface.co/deejaynof/model_bs_roformer_ep_317_sdr_12.9755/resolve/main/model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "filename":    "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "subdir":      "audio_separator",
        "size_mb":     610,
        "sha256":      None,
        "required":    True,
        "description": "Band-Split RoFormer transformer for vocal isolation (SDR 12.97)",
    },
    {
        "id":          "gs_prism_bsroformer_yaml",
        "name":        "GS-PRISM Config",
        "stage":       "SEPARATE",
        "source":      "direct",
        "url":         "https://raw.githubusercontent.com/TRvlvr/model_repo/main/model_data/model_bs_roformer_ep_317_sdr_12.9755.yaml",
        "filename":    "model_bs_roformer_ep_317_sdr_12.9755.yaml",
        "subdir":      "audio_separator",
        "size_mb":     0.01,
        "sha256":      None,
        "required":    True,
        "description": "BS-RoFormer model configuration YAML",
    },

    # ── GS-REFINE (Diff-HierVC vocal refinement) ──────────────────────────
    {
        "id":          "gs_refine_diffhier",
        "name":        "GS-REFINE (Diff-HierVC)",
        "stage":       "REFINE",
        "source":      "direct",
        "url":         "https://huggingface.co/Plachta/Diff-HierVC/resolve/main/model_diffhier.pth",
        "filename":    "model_diffhier.pth",
        "subdir":      "diff_hiervc",
        "size_mb":     70,
        "sha256":      None,
        "required":    True,
        "description": "Hierarchical diffusion model for vocal refinement",
    },
    {
        "id":          "gs_refine_vocoder",
        "name":        "GS-REFINE Vocoder (BigvGAN 16kHz)",
        "stage":       "REFINE",
        "source":      "direct",
        "url":         "https://huggingface.co/Plachta/Diff-HierVC/resolve/main/voc_bigvgan.pth",
        "filename":    "voc_bigvgan.pth",
        "subdir":      "diff_hiervc",
        "size_mb":     592,
        "sha256":      None,
        "required":    True,
        "description": "BigvGAN neural vocoder for Diff-HierVC (16kHz)",
    },

    # ── GS-CRYSTAL (VoiceRestore transformer-diffusion) ───────────────────
    {
        "id":          "gs_crystal_voicerestore",
        "name":        "GS-CRYSTAL (VoiceRestore)",
        "stage":       "DENOISE",
        "source":      "huggingface",
        "repo_id":     "jadechoghari/VoiceRestore",
        "filename":    "pytorch_model.bin",
        "subdir":      "voicerestore",
        "size_mb":     1100,
        "sha256":      None,
        "required":    True,
        "description": "Flow-matching transformer for voice restoration (301M params)",
    },
    {
        "id":          "gs_crystal_bigvgan",
        "name":        "GS-VOCODER (BigVGAN v2 24kHz)",
        "stage":       "DENOISE",
        "source":      "huggingface",
        "repo_id":     "nvidia/bigvgan_v2_24khz_100band_256x",
        "filename":    "bigvgan_generator.pt",
        "subdir":      "huggingface",
        "size_mb":     450,
        "sha256":      None,
        "required":    True,
        "description": "NVIDIA BigVGAN v2 vocoder for VoiceRestore output",
    },

    # ── GS-ASCEND (AudioSR latent diffusion upscaler) ─────────────────────
    {
        "id":          "gs_ascend_audiosr",
        "name":        "GS-ASCEND (AudioSR Basic)",
        "stage":       "UPSCALE",
        "source":      "huggingface",
        "repo_id":     "haoheliu/audiosr_basic",
        "filename":    "pytorch_model.bin",
        "subdir":      "huggingface",
        "size_mb":     5800,
        "sha256":      None,
        "required":    True,
        "description": "Latent diffusion super-resolution (44.1kHz → 48kHz)",
    },

    # ── XLS-R-300M (Wav2Vec2 content encoder for Diff-HierVC) ─────────────
    {
        "id":          "xlsr_300m",
        "name":        "XLS-R-300M (Content Encoder)",
        "stage":       "REFINE",
        "source":      "huggingface",
        "repo_id":     "facebook/wav2vec2-xls-r-300m",
        "filename":    "pytorch_model.bin",
        "subdir":      "huggingface",
        "size_mb":     1180,
        "sha256":      None,
        "required":    True,
        "description": "Facebook XLS-R 300M frozen content encoder",
    },

    # ── PhaseLimiter (AI mastering binary — Stage 7 MASTER) ────────────
    {
        "id":          "phaselimiter_binary",
        "name":        "PhaseLimiter AI (Mastering Engine)",
        "stage":       "MASTER",
        "source":      "phaselimiter",
        "urls": {
            "Windows": "https://github.com/ai-mastering/phaselimiter/releases/download/v0.2.0/phaselimiter-win.zip",
            "Linux":   "https://github.com/ai-mastering/phaselimiter/releases/download/v0.2.0/release.tar.xz",
            "Darwin":  "build_from_source",
        },
        "filename":    "phase_limiter",
        "subdir":      "phaselimiter",
        "size_mb":     50,
        "sha256":      None,
        "required":    True,
        "description": "AI mastering engine — phase-coherent limiter + loudness matching (bakuage.com/aimastering.com)",
    },
]


# ── Registry API ─────────────────────────────────────────────────────────────

def get_model_path(model_entry: dict) -> str:
    """Return the expected filesystem path for a model entry."""
    base = get_models_base()
    return os.path.join(base, model_entry["subdir"], model_entry["filename"])


def get_phaselimiter_install_dir() -> str:
    """Canonical install directory for the phase_limiter binary."""
    engine_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(engine_dir, "modules", "external", "phase", "bin", "Release")


def get_phaselimiter_binary_path() -> str:
    """Full path to the installed phase_limiter binary."""
    name = "phase_limiter.exe" if platform.system() == "Windows" else "phase_limiter"
    return os.path.join(get_phaselimiter_install_dir(), name)


def check_model_installed(model_entry: dict) -> bool:
    """Check if a model file exists at its expected path."""
    if model_entry["source"] == "phaselimiter":
        return _check_phaselimiter()
    if model_entry["source"] == "huggingface":
        return _check_hf_model(model_entry)
    path = get_model_path(model_entry)
    return os.path.exists(path)


def _check_phaselimiter() -> bool:
    """Check if the phase_limiter binary is installed and executable."""
    binary = get_phaselimiter_binary_path()
    return os.path.isfile(binary) and os.access(binary, os.X_OK)


def _check_hf_model(model_entry: dict) -> bool:
    """Check if a HuggingFace model exists in the cache."""
    base = get_models_base()
    hf_cache = os.path.join(base, "huggingface", "hub")
    repo_id = model_entry.get("repo_id", "")
    # HF Hub stores as models--org--name
    cache_name = f"models--{repo_id.replace('/', '--')}"
    cache_dir = os.path.join(hf_cache, cache_name)
    if not os.path.isdir(cache_dir):
        return False
    # Check snapshots dir has content
    snapshots = os.path.join(cache_dir, "snapshots")
    if not os.path.isdir(snapshots):
        return False
    for root, dirs, files in os.walk(snapshots):
        if files:
            return True
    return False


def check_all_models() -> dict:
    """
    Check installation status of all models.
    Returns dict compatible with Tauri IPC.
    """
    results = []
    total_size_mb = 0
    missing_size_mb = 0
    all_installed = True

    for model in MODELS:
        installed = check_model_installed(model)
        if not installed:
            all_installed = False
            missing_size_mb += model["size_mb"]
        total_size_mb += model["size_mb"]
        results.append({
            "id":          model["id"],
            "name":        model["name"],
            "stage":       model["stage"],
            "size_mb":     model["size_mb"],
            "installed":   installed,
            "required":    model["required"],
            "description": model["description"],
        })

    return {
        "all_installed":   all_installed,
        "models":          results,
        "total_size_mb":   total_size_mb,
        "missing_size_mb": missing_size_mb,
        "models_dir":      get_models_base(),
    }


def get_missing_models() -> list:
    """Return list of model entries that are not yet installed."""
    return [m for m in MODELS if not check_model_installed(m)]


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    status = check_all_models()
    print(f"Models directory: {status['models_dir']}")
    print(f"Total: {status['total_size_mb']/1024:.1f} GB")
    print(f"Missing: {status['missing_size_mb']/1024:.1f} GB")
    print(f"All installed: {status['all_installed']}\n")
    for m in status["models"]:
        icon = "[OK]" if m["installed"] else "✗"
        print(f"  [{icon}] {m['name']} ({m['size_mb']}MB) — {m['stage']}")
