# VOXIS V4.0.0 DENSE — Trinity Engine Distribution

## Quick Start

```bash
# 1. Install Python dependencies
pip install torch torchaudio pedalboard audio-separator deepfilternet audiosr numpy

# 2. Install models from distro/ (first time only)
python3 setup_models.py

# 3. Run the pipeline
python3 trinity_core.py --input your_audio.wav --output restored.wav
```

## Distribution Structure

```
trinity_engine/
├── trinity_core.py          # Main pipeline orchestrator
├── download_models.py       # Download all models
├── setup_models.py          # First-run model setup from distro/
│
├── modules/                 # Pipeline stages
│   ├── ingest.py            # Stage 1: FFmpeg decode
│   ├── uvr_processor.py     # Stage 2: BS-RoFormer separation
│   ├── spectrum_analyzer.py # Stage 2.5: Noise profiling
│   ├── deep_filter.py       # Stage 3/5: DeepFilterNet3 denoise
│   ├── upsampler.py         # Stage 4: AudioSR super-resolution
│   ├── mastering_phase.py   # Stage 6: Pedalboard mastering
│   ├── device_utils.py      # Cross-platform GPU detection
│   ├── pipeline_cache.py    # SHA-256 stage caching
│   ├── retry_engine.py      # Exponential backoff + CPU fallback
│   ├── error_telemetry.py   # Error logging + sync
│   └── onnx_separator.py    # ONNX RT fallback separator
│
├── distro/                  # Distribution models (12.1 GB)
│   └── models/
│       ├── audio_separator/ # BS-RoFormer weights (~610 MB)
│       ├── deepfilternet/   # DeepFilterNet3 checkpoints (~8 MB)
│       └── audiosr/         # AudioSR latent diffusion (~11.5 GB)
│
├── dependencies/            # Runtime model cache (auto-created)
│   ├── models/              # Installed model weights
│   ├── stage_cache/         # Pipeline SHA-256 cache
│   └── error_cache/         # Error telemetry cache
│
└── trinity_temp/            # Working directory (auto-purged)
```

## Pipeline Stages

| # | Stage | Model | Time |
|---|-------|-------|------|
| 1 | INGEST | FFmpeg | <1s |
| 2 | SEPARATE | BS-RoFormer (639MB) | ~10s |
| 2.5 | ANALYZE | Spectral Profiler | <0.1s |
| 3 | DENOISE (Pre) | DeepFilterNet3 | ~0.5s |
| 4 | UPSCALE | AudioSR Diffusion (48kHz) | ~18s |
| 5 | DENOISE (Post) | DeepFilterNet3 | ~0.5s |
| 6 | MASTER | Pedalboard (limiter + width) | <0.1s |
| 7 | EXPORT | FFmpeg (WAV/FLAC/mux) | <0.1s |

**Total: ~30s** for a 5-second audio file on Apple M-series.

## CLI Options

```bash
python3 trinity_core.py \
  --input <file>           # Input audio/video
  --output <file>          # Output path
  --extreme                # Extreme denoise mode
  --stereo-width 0.80      # Stereo width (0.0–1.0)
  --format WAV             # WAV or FLAC
```

## System Requirements

- **macOS**: Apple Silicon (M1/M2/M3), 16GB+ RAM
- **Windows**: NVIDIA GPU (CUDA), 16GB+ RAM
- **Storage**: 13GB for models + working space
- **FFmpeg**: Required (brew install ffmpeg / choco install ffmpeg)
- **Python**: 3.10+

## Model Management

```bash
# Check which models are installed
python3 download_models.py --check

# Download all models from the internet
python3 download_models.py

# Copy models to distro/ for distribution
python3 download_models.py --distro

# Install models from distro/ (for end users)
python3 setup_models.py
```

---

**Copyright © 2026 Glass Stone LLC. All Rights Reserved.**
**CEO: Gabriel B. Rodriguez | York, PA**
**Powered by Trinity V8.2**
