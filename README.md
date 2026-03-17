# VOXIS 4.0 DENSE

**Powered by Trinity V8.1 | Built by Glass Stone LLC**
**CEO: Gabriel B. Rodriguez | York, PA | © 2026**
coded with help from Claude 4.6 opus , Google Gemini was used to prototype the Ui , it was mostly built by hand . 
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

## Installing on a New Device

### Option A — DMG Installer (End Users, macOS)

1. Download `Voxis 4.0 DENSE-4.0.0-arm64.dmg` from the [Releases](../../releases) page
2. Open the DMG and drag **Voxis 4.0 DENSE** to `/Applications`
3. On first launch, right-click → Open (bypasses Gatekeeper on first run)
4. No additional dependencies required — everything is bundled

> **Note:** First launch may take 10–30 seconds while the Trinity Engine unpacks.
> Requires macOS 12.0+ and Apple M-series chip.

---

### Option B — Build from Source (Developers, macOS)

#### 1. System Prerequisites

```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required system tools
brew install python@3.11 node ffmpeg git

# Verify
python3 --version   # must be 3.11+
node --version      # must be 20+
ffmpeg -version
```

#### 2. Clone Repository

```bash
git clone --recurse-submodules https://github.com/GlassStoneLabs/VOXIS.git
cd VOXIS
```

#### 3. Install Python Dependencies

```bash
# Pin versions required for binary compatibility
pip3 install "setuptools==69.5.1" "numpy<2.0"
pip3 install -r trinity_engine/requirements.txt
pip3 install pyinstaller
```

#### 4. Run the Automated Build

```bash
./build_scripts/build_voxis_desktop.sh
```

This will:
- Compile `trinity_v8_core` binary via PyInstaller (~5–15 min, requires GPU memory)
- Bundle binary into `app/resources/bin/`
- Build the Electron frontend (`npm run electron:build`)
- Output DMG to `app/release/`

#### 5. Skip Python build (if binary already exists)

```bash
./build_scripts/build_voxis_desktop.sh --skip-python
```

---

### Option C — Dev Mode (Hot Reload)

```bash
cd app
npm install
npm run electron:dev   # Vite dev server + Electron with hot reload
```

> Requires `app/resources/bin/trinity_v8_core` binary to exist for engine features.
> Build it once with `./build_scripts/build_voxis_desktop.sh --skip-deps` first.

---

## Known Build Notes

| Issue | Fix |
|-------|-----|
| `pkg_resources.NullProvider` crash | Pin `setuptools==69.5.1` before PyInstaller build |
| `numpy.core._multiarray_umath` crash | Pin `numpy<2.0` before PyInstaller build |
| First launch slow | Normal — Trinity Engine unpacks on first run |
| Gatekeeper blocks on macOS | Right-click → Open on first launch |

---

## Platforms

| Platform | Status | Installer |
|----------|--------|-----------|
| macOS M-Series | ✓ Primary | `.dmg` |
| Windows x86_64 | Planned | `.exe` (NSIS) |

---

## Architecture

```
Voxis V4.0.0 DENSE
├── app/                       Frontend (Electron + React/TypeScript, Bauhaus UI)
│   ├── electron/
│   │   ├── main.ts            Window management, IPC, sidecar spawn
│   │   └── preload.ts         Context bridge (window.electronAPI)
│   ├── src/
│   │   ├── App.tsx            Bauhaus UI — 5 inline modules
│   │   └── Bauhaus.css        Design system tokens and layout
│   └── resources/bin/         trinity_v8_core binary (not in git — build or download)
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
├── build_scripts/
│   └── build_voxis_desktop.sh  Full build automation
└── trinity_v8_core.spec        PyInstaller freeze spec
```

> **Binary note:** `trinity_v8_core` (~630MB) is not tracked in git.
> Build via `./build_scripts/build_voxis_desktop.sh` or download from Releases.

---

## Copyright

Copyright © 2026 Glass Stone LLC. All Rights Reserved.
CEO: Gabriel B. Rodriguez | York, PA

See `LICENSE.md` for full terms.

---

*VOXIS 4.0 DENSE — No demos. Fully functional professional software.*
