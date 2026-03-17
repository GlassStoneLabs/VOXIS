import httpx
import hashlib
from pathlib import Path
from huggingface_hub import hf_hub_download

MANIFEST = {
    # FROM YOUR WEBSITE (small, fast, version-controlled)
    "voxis_config.json":    {"source": "website",  "url": "https://yoursite.com/assets/voxis_config.json",   "sha256": "abc123"},
    "ffmpeg_mac":           {"source": "website",  "url": "https://yoursite.com/assets/ffmpeg_aarch64",      "sha256": "def456"},
    "ffmpeg_win":           {"source": "website",  "url": "https://yoursite.com/assets/ffmpeg_x86.exe",      "sha256": "ghi789"},

    # FROM HUGGING FACE (heavy models — free hosting)
    "mel_band_roformer.onnx": {"source": "hf",    "repo": "GlassStone/voxis-dense-v4", "filename": "mel_band_roformer.onnx", "sha256": "..."},
    "mp_senet.onnx":          {"source": "hf",    "repo": "GlassStone/voxis-dense-v4", "filename": "mp_senet.onnx",          "sha256": "..."},
    "hifi_sr.onnx":           {"source": "hf",    "repo": "GlassStone/voxis-dense-v4", "filename": "hifi_sr.onnx",           "sha256": "..."},
    "voicerestore.onnx":      {"source": "hf",    "repo": "GlassStone/voxis-dense-v4", "filename": "voicerestore.onnx",      "sha256": "..."},
}

FALLBACK_BASE = "https://your-r2-bucket.r2.dev/"  # Cloudflare R2


def verify_license(key: str) -> bool:
    """Hit YOUR server to verify the license key."""
    r = httpx.post("https://yoursite.com/api/verify-license", json={"key": key})
    return r.status_code == 200 and r.json().get("valid")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(name: str, info: dict, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / name

    # Skip if already downloaded and valid
    if out.exists() and sha256_file(out) == info["sha256"]:
        print(f"✓ {name} already verified")
        return

    try:
        if info["source"] == "hf":
            hf_hub_download(
                repo_id=info["repo"],
                filename=info["filename"],
                local_dir=str(dest)
            )
        else:  # website
            with httpx.stream("GET", info["url"]) as r:
                with open(out, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
    except Exception as e:
        print(f"⚠ Primary failed for {name}: {e}. Trying fallback...")
        # FALLBACK to Cloudflare R2
        fallback_url = FALLBACK_BASE + name
        with httpx.stream("GET", fallback_url) as r:
            with open(out, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)

    # Verify hash
    assert sha256_file(out) == info["sha256"], f"Hash mismatch for {name}!"
    print(f"✓ {name} downloaded and verified")


def run_setup(license_key: str, install_dir: Path):
    if not verify_license(license_key):
        raise PermissionError("Invalid or expired license key.")

    print("License verified. Starting download...")
    for name, info in MANIFEST.items():
        download_file(name, info, install_dir)

    print("✓ VOXIS V4.0.0 DENSE setup complete.")
