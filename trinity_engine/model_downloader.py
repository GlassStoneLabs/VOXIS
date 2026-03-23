#!/usr/bin/env python3
"""
VOXIS V4.0.0 DENSE — Robust Model Downloader
Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez

Downloads all required ML models on first launch with:
  - Progress reporting (stdout for Tauri event streaming)
  - SHA-256 verification
  - Retry with exponential backoff
  - Resume support for interrupted downloads
  - HuggingFace Hub integration for HF-hosted models
  - Direct HTTP download for other models

Output protocol (parsed by Tauri host):
  [MODEL_STATUS] {"event":"...", "id":"...", ...}
  Regular print lines for human-readable log
"""

import os
import sys
import json
import time
import hashlib
import platform

from model_registry import (
    MODELS, get_models_base, get_model_path,
    check_model_installed, check_all_models, get_missing_models,
)


# ── Configuration ────────────────────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BACKOFF_SEC = [5, 15, 30]
CHUNK_SIZE = 1024 * 1024  # 1MB download chunks
HF_CACHE_DIR = None  # Set in _init_hf_cache()


# ── Structured Event Emitter ─────────────────────────────────────────────────

def emit(event: str, **kwargs):
    """Emit structured JSON event on stdout for Tauri to parse."""
    payload = {"event": event, **kwargs}
    print(f"[MODEL_STATUS] {json.dumps(payload)}", flush=True)


# ── HuggingFace Hub Setup ────────────────────────────────────────────────────

def _init_hf_cache():
    global HF_CACHE_DIR
    base = get_models_base()
    HF_CACHE_DIR = os.path.join(base, "huggingface")
    os.makedirs(HF_CACHE_DIR, exist_ok=True)
    os.environ["HUGGINGFACE_HUB_CACHE"] = HF_CACHE_DIR
    os.environ["HF_HUB_CACHE"] = HF_CACHE_DIR
    os.environ["TRANSFORMERS_CACHE"] = HF_CACHE_DIR
    os.environ["HF_HOME"] = HF_CACHE_DIR


# ── Download: Direct HTTP ────────────────────────────────────────────────────

def download_direct(model: dict) -> bool:
    """Download a model via direct HTTP URL with progress and resume."""
    import urllib.request
    import urllib.error

    dest_path = get_model_path(model)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    url = model["url"]
    model_id = model["id"]
    model_name = model["name"]
    expected_size = model["size_mb"] * 1024 * 1024  # approximate

    # Check for partial download (resume support)
    temp_path = dest_path + ".partial"
    resume_from = 0
    if os.path.exists(temp_path):
        resume_from = os.path.getsize(temp_path)
        print(f"[Downloader] Resuming {model_name} from {resume_from/(1024*1024):.1f}MB")

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url)
            if resume_from > 0:
                req.add_header("Range", f"bytes={resume_from}-")

            with urllib.request.urlopen(req, timeout=60) as response:
                total = response.headers.get("Content-Length")
                if total:
                    total = int(total) + resume_from
                else:
                    total = expected_size

                mode = "ab" if resume_from > 0 else "wb"
                downloaded = resume_from

                with open(temp_path, mode) as f:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        pct = min(100.0, downloaded * 100 / total) if total > 0 else 0
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total / (1024 * 1024)
                        emit("progress", id=model_id, name=model_name,
                             pct=round(pct, 1), mb_done=round(mb_done, 1),
                             mb_total=round(mb_total, 1))

            # Move completed download to final path
            os.replace(temp_path, dest_path)
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            emit("downloaded", id=model_id, name=model_name, size_mb=round(size_mb, 1))
            return True

        except (urllib.error.URLError, OSError, TimeoutError) as e:
            wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
            emit("retry", id=model_id, name=model_name,
                 attempt=attempt + 1, max_retries=MAX_RETRIES,
                 error=str(e), wait_sec=wait)
            print(f"[Downloader] Attempt {attempt+1}/{MAX_RETRIES} failed: {e}")
            print(f"[Downloader] Retrying in {wait}s...")
            # Update resume position for next attempt
            if os.path.exists(temp_path):
                resume_from = os.path.getsize(temp_path)
            time.sleep(wait)

    emit("error", id=model_id, name=model_name,
         error=f"Failed after {MAX_RETRIES} attempts")
    return False


# ── Download: HuggingFace Hub ────────────────────────────────────────────────

def download_huggingface(model: dict) -> bool:
    """Download a model via HuggingFace Hub with caching."""
    model_id = model["id"]
    model_name = model["name"]
    repo_id = model["repo_id"]

    emit("downloading", id=model_id, name=model_name,
         source="huggingface", repo=repo_id)

    for attempt in range(MAX_RETRIES):
        try:
            # Special handling for BigVGAN (uses from_pretrained with custom loading)
            if "bigvgan" in repo_id.lower() and "nvidia" in repo_id.lower():
                from huggingface_hub import snapshot_download
                snapshot_download(
                    repo_id,
                    cache_dir=HF_CACHE_DIR,
                    local_dir_use_symlinks=True,
                )
            else:
                from huggingface_hub import hf_hub_download
                hf_hub_download(
                    repo_id=repo_id,
                    filename=model["filename"],
                    cache_dir=HF_CACHE_DIR,
                )

            emit("downloaded", id=model_id, name=model_name,
                 source="huggingface", repo=repo_id)
            return True

        except Exception as e:
            wait = RETRY_BACKOFF_SEC[min(attempt, len(RETRY_BACKOFF_SEC) - 1)]
            emit("retry", id=model_id, name=model_name,
                 attempt=attempt + 1, max_retries=MAX_RETRIES,
                 error=str(e), wait_sec=wait)
            print(f"[Downloader] HF download failed: {e}")
            time.sleep(wait)

    emit("error", id=model_id, name=model_name,
         error=f"HuggingFace download failed after {MAX_RETRIES} attempts")
    return False


# ── SHA-256 Verification ─────────────────────────────────────────────────────

def verify_sha256(file_path: str, expected_hash: str) -> bool:
    """Verify file integrity via SHA-256."""
    if not expected_hash:
        return True  # No hash to verify against

    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            sha.update(chunk)
    actual = sha.hexdigest()
    if actual != expected_hash:
        emit("hash_mismatch", path=file_path,
             expected=expected_hash, actual=actual)
        return False
    return True


# ── Orchestrator ─────────────────────────────────────────────────────────────

def update_all_models() -> dict:
    """Clear all installed models to force a fresh redownload of the latest weights."""
    print("\n=== VOXIS Model Update ===")
    print("Clearing cached ML models...")
    _init_hf_cache()
    import shutil
    base = get_models_base()
    for d in ["audio_separator", "huggingface", "voicerestore"]:
        p = os.path.join(base, d)
        if os.path.exists(p):
            shutil.rmtree(p)
            print(f"Removed cache: {d}")
    
    df_paths = [
        os.path.expanduser("~/Library/Caches/DeepFilterNet"),
        os.path.expanduser("~/.cache/DeepFilterNet"),
    ]
    for p in df_paths:
        if os.path.exists(p):
            shutil.rmtree(p)
            print(f"Removed cache: DeepFilterNet")
            
    print("Cache cleared. Initiating fresh download...")
    return download_all_models()

def download_all_models() -> dict:
    """
    Download all missing models. Returns summary dict.
    Streams progress events to stdout for Tauri.
    """
    _init_hf_cache()

    missing = get_missing_models()
    total = len(missing)

    if total == 0:
        emit("complete", downloaded=0, failed=0)
        print("[Downloader] All models already installed.")
        return {"success": True, "downloaded": 0, "failed": 0}

    total_size_mb = sum(m["size_mb"] for m in missing)
    print(f"\n{'='*60}")
    print(f"  VOXIS V4.0.0 DENSE — Model Download")
    print(f"  {total} models · ~{total_size_mb/1024:.1f} GB")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print(f"{'='*60}\n")

    emit("start", total=total, total_size_mb=total_size_mb)

    downloaded = 0
    failed = 0
    failed_models = []

    for i, model in enumerate(missing):
        model_name = model["name"]
        model_id = model["id"]
        source = model["source"]

        print(f"\n[{i+1}/{total}] Downloading {model_name} ({model['size_mb']}MB)...")
        emit("downloading", id=model_id, name=model_name,
             index=i, total=total, source=source)

        if source == "direct":
            success = download_direct(model)
        elif source == "huggingface":
            success = download_huggingface(model)
        else:
            print(f"[Downloader] Unknown source: {source}")
            success = False

        if success:
            # Verify checksum if provided
            if model.get("sha256") and source == "direct":
                path = get_model_path(model)
                if not verify_sha256(path, model["sha256"]):
                    print(f"[Downloader] ✗ Checksum failed for {model_name}")
                    os.remove(path)
                    success = False

        if success:
            downloaded += 1
            print(f"[Downloader] [OK] {model_name}")
        else:
            failed += 1
            failed_models.append(model_name)
            print(f"[Downloader] ✗ {model_name} FAILED")

    # Copy audio-separator metadata files if BS-RoFormer was downloaded
    _ensure_separator_metadata()

    emit("complete", downloaded=downloaded, failed=failed,
         failed_models=failed_models)

    print(f"\n{'='*60}")
    print(f"  Download Complete: {downloaded} OK, {failed} failed")
    if failed_models:
        print(f"  Failed: {', '.join(failed_models)}")
    print(f"{'='*60}\n")

    return {
        "success": failed == 0,
        "downloaded": downloaded,
        "failed": failed,
        "failed_models": failed_models,
    }


def _ensure_separator_metadata():
    """
    Ensure audio-separator has the metadata files it needs
    (model_data JSON registries) alongside the BS-RoFormer model.
    """
    base = get_models_base()
    sep_dir = os.path.join(base, "audio_separator")
    if not os.path.isdir(sep_dir):
        return

    # Create minimal download_checks.json if missing
    checks_path = os.path.join(sep_dir, "download_checks.json")
    if not os.path.exists(checks_path):
        with open(checks_path, "w") as f:
            json.dump({"version": "UVR_Patch_10_6_23_4_27"}, f)


# ── Check-only mode ─────────────────────────────────────────────────────────

def check_models_json() -> str:
    """Return model status as JSON (for Tauri IPC)."""
    _init_hf_cache()
    status = check_all_models()
    return json.dumps(status)


# ── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VOXIS Model Downloader")
    parser.add_argument("--check", action="store_true", help="Check model status only")
    parser.add_argument("--download", action="store_true", help="Download all missing models")
    parser.add_argument("--update", action="store_true", help="Force wipe and redownload all models")
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    args = parser.parse_args()

    if args.check or args.json:
        if args.json:
            print(check_models_json())
        else:
            _init_hf_cache()
            status = check_all_models()
            print(f"Models dir: {status['models_dir']}")
            print(f"Total: {status['total_size_mb']/1024:.1f} GB | "
                  f"Missing: {status['missing_size_mb']/1024:.1f} GB")
            for m in status["models"]:
                icon = "[OK]" if m["installed"] else "✗"
                print(f"  [{icon}] {m['name']} ({m['size_mb']}MB)")
    elif args.download:
        result = download_all_models()
        sys.exit(0 if result["success"] else 1)
    elif args.update:
        result = update_all_models()
        sys.exit(0 if result["success"] else 1)
    else:
        parser.print_help()
