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
| 2 | **Separate** | Glass Stone Separator — BS-RoFormer vocal extraction |
| 3 | **Analyze** | Spectrum & RMS noise profiling with Auto-EQ detection |
| 4 | **Denoise** | DeepFilterNet3 — HIGH (48dB) or EXTREME (100dB) |
| 5 | **Upscale** | AudioSR latent diffusion → 48kHz stereo |
| 6 | **Master** | Phase Limiter + Stereo Width (Pedalboard) |
| 7 | **Export** | 24-bit WAV or FLAC |

---

## Platforms

| Platform | Status | Installer |
|----------|--------|-----------|
| macOS M-Series | Primary | `.dmg` |
| Windows x86_64 | Secondary | `.exe` (planned) |

---

## Build

```bash
# Full build (compiles engine + builds DMG installer)
./build_scripts/build_voxis_desktop.sh

# Skip Python build (if binary already exists at app/resources/bin/trinity_v8_core)
./build_scripts/build_voxis_desktop.sh --skip-python

# Clean build
./build_scripts/build_voxis_desktop.sh --clean
```

**Prerequisites:** Python 3.11+, Node.js 20+, FFmpeg (`brew install ffmpeg`), Git.

---

## Architecture

```
Voxis V4.0.0 DENSE
├── app/                       Frontend (Electron + React/TypeScript, Bauhaus UI)
│   ├── electron/              Electron main process & preload bridge
│   │   ├── main.ts            Window management, IPC, sidecar spawn
│   │   └── preload.ts         Context bridge (window.electronAPI)
│   ├── src/
│   │   ├── App.tsx            Bauhaus UI — all 5 modules inline
│   │   └── Bauhaus.css        Design system tokens and layout
│   └── resources/bin/         Trinity V8.1 compiled binary (not in git — see below)
├── trinity_engine/            Python Backend — Trinity V8.1 Engine
│   ├── trinity_core.py        Pipeline orchestrator
│   └── modules/
│       ├── ingest.py          FFmpeg decode/export
│       ├── uvr_processor.py   Glass Stone Separator (BS-RoFormer)
│       ├── spectrum_analyzer.py
│       ├── voicerestore_wrapper.py  DeepFilterNet3
│       ├── upsampler.py       AudioSR latent diffusion
│       ├── mastering_phase.py Pedalboard limiter + stereo width
│       └── device_utils.py    Apple Silicon MPS optimizer
├── build_scripts/             Build automation
│   └── build_voxis_desktop.sh
└── trinity_v8_core.spec       PyInstaller spec
```

> **Note:** The `trinity_v8_core` binary (~600MB) is not tracked in git.
> Build it with `./build_scripts/build_voxis_desktop.sh` or download from Releases.

---

## Dev Mode

```bash
cd app
npm install
npm run electron:dev   # starts Vite + Electron with hot reload
```

---

## Copyright

Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez | York, PA

See `LICENSE.md` for full terms.

---

*VOXIS 4.0 DENSE — No demos. Fully functional professional software.*
