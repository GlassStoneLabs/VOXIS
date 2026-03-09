# VOXIS 4.0 DENSE

**Powered by Trinity V8.1 | Built by Glass Stone LLC**
**CEO: Gabriel B. Rodriguez | York, PA | © 2026**

---

## Overview

Voxis 4.0 DENSE is a professional-grade desktop application for audio restoration and
enhancement. It transforms degraded, low-quality audio into clean, high-resolution
stereo output through a multi-stage AI pipeline driven by the Trinity V8.1 engine.

Designed following strict Bauhaus UI principles: form follows function, primary palette,
geometric grid, zero ornament.

---

## The Trinity V8.1 Pipeline

| Step | Module | Technology |
|------|--------|------------|
| 1 | **Ingest** | FFmpeg universal decoder (WAV, MP3, MP4, MOV, MKV) |
| 2 | **Separate** | Glass Stone Separator — Mel-Band RoFormer (BS-RoFormer) |
| 3 | **Analyze** | Spectrum & RMS noise profiling |
| 4 | **Denoise** | DeepFilterNet3 — HIGH (48dB) or EXTREME (100dB) |
| 5 | **Upscale** | AudioSR latent diffusion → 48kHz stereo |
| 6 | **Master** | Phase Limiter + Stereo Width (Pedalboard) |
| 7 | **Export** | 24-bit WAV or FLAC |

---

## Platforms

| Platform | Status | Installer |
|----------|--------|-----------|
| macOS M-Series | Primary | `.dmg` |
| Windows x86_64 | Secondary | `.exe` (NSIS) |

---

## Build

```bash
# Full build (downloads deps, compiles engine, builds installer)
./build_scripts/build_voxis_desktop.sh

# Skip dependency install (if already installed)
./build_scripts/build_voxis_desktop.sh --skip-deps

# Tauri frontend only (if engine binary already exists)
./build_scripts/build_voxis_desktop.sh --tauri-only

# Clean build
./build_scripts/build_voxis_desktop.sh --clean
```

Prerequisites: Python 3.11+, Node.js 20+, Rust (stable), FFmpeg, Git.

---

## Architecture

```
Voxis V4.0.0 DENSE
├── app/                    Frontend (Tauri + React/TypeScript, Bauhaus UI)
│   └── src-tauri/          Rust host — sidecar management, event streaming
├── trinity_engine/         Python Backend — Trinity V8 Engine
│   ├── trinity_core.py     Pipeline orchestrator
│   └── modules/
│       ├── ingest.py       FFmpeg decode/export
│       ├── uvr_processor.py   Glass Stone Separator
│       ├── spectrum_analyzer.py
│       ├── denoiser.py     DeepFilterNet3
│       ├── upsampler.py    AudioSR
│       ├── mastering.py    Pedalboard
│       └── mps_utils.py    Apple Silicon MPS optimizer
├── build_scripts/          Build automation
└── trinity_v8_core.spec    PyInstaller spec
```

---

## Copyright

Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez | York, PA

See `LICENSE.md` for full terms.

---

*VOXIS 4.0 DENSE — No demos. Fully functional professional software.*
