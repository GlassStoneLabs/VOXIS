# VOXIS V4.0.0 DENSE — System Architecture
**Glass Stone LLC © 2026 | Powered by Trinity V8.1**

---

## Overview

VOXIS is a professional voice restoration desktop application. It consists of three layers:

1. **Electron Shell** — native OS integration, file I/O, IPC orchestration
2. **React Frontend** — Bauhaus-style UI, real-time pipeline feedback
3. **Trinity V8.1 Engine** — Python ML pipeline frozen into a portable binary

---

## Layer 1 — Electron Shell
`app/electron/main.ts` · `app/electron/preload.ts`

### Main Process (`main.ts`)
- Window: 1120×820, `titleBarStyle: hiddenInset`, `contextIsolation: true`
- `app.setName('Voxis 4.0 DENSE')` — overrides OS-level app name
- `voxis-file://` custom protocol — memory-efficient local audio streaming
- `autoUpdater` (electron-updater) — GitHub Releases, manual prompt, no silent download
- `child_process.spawn()` — launches `trinity_v8_core` binary with piped stdio
- MP3 post-process: engine outputs WAV → FFmpeg converts to 320kbps MP3

### IPC Channels

| Channel | Direction | Description |
|---------|-----------|-------------|
| `dialog:openFile` | invoke | Native open-file dialog (voice & audio filters) |
| `dialog:saveFile` | invoke | Native save-as dialog |
| `trinity:runEngine` | invoke | Spawn Trinity engine, return output path |
| `trinity:cancelEngine` | invoke | SIGTERM active engine process |
| `trinity:getVersion` | invoke | Return version string |
| `shell:openPath` | invoke | Reveal file in Finder/Explorer |
| `shell:openFile` | invoke | Open file in default app |
| `file:copy` | invoke | Async file copy (Save As) |
| `update:download` | invoke | Trigger update download |
| `update:install` | invoke | Quit and install update |
| `trinity-log` | send → renderer | Stream engine stdout/stderr line-by-line |
| `trinity-done` | send → renderer | Engine completed, emit output path |
| `update-status` | send → renderer | Update availability/progress/downloaded |

### Context Bridge (`preload.ts`)
```typescript
window.electronAPI = {
  dialog  : { openFile, saveFile },
  trinity : { runEngine, cancelEngine, getVersion, onLog, offLog, onDone, offDone },
  shell   : { openPath, openFile },
  file    : { copy, toPreviewUrl },     // toPreviewUrl → voxis-file://...
  update  : { onStatus, offStatus, download, install }
}
```

---

## Layer 2 — React Frontend
`app/src/App.tsx` · `app/src/Bauhaus.css`

**Stack:** React 19 · TypeScript 5.8 · Vite 7 · Framer Motion 12 · Bauhaus.css

### UI Layout
```
┌─ Header ─────────────────────────────────────────┐
│  [Bauhaus Logo]  VOXIS DENSE  BY GLASS STONE  ●  │
├─ Sidebar (210px) ─┬─ Main Panel ─────────────────┤
│  Processing Mode  │  File Strip + Audio Preview   │
│  Upscale Factor   │  Status + EQ Readout Chips    │
│  Output Format    │  Pipeline Steps (7 stages)    │
│  Denoise Strength │  Progress Bar + Elapsed Time  │
│  Noise Profile    │  Log Viewer (200 line buffer) │
│  Restoration Steps│  Action Bar                   │
│  Generation Guide │                               │
│  High Precision   │  [Completion Overlay]         │
│  Stereo Output    │   ✓ VOICE RESTORED            │
│  RAM Limit        │   Export / Reveal / New       │
└───────────────────┴───────────────────────────────┘
```

### Key State
| State | Type | Purpose |
|-------|------|---------|
| `status` | `idle\|running\|done\|error` | Pipeline lifecycle |
| `currentStep` | `number` | Active pipeline step (1–7) |
| `logs` | `string[]` | Engine stdout/stderr (200 line buffer) |
| `processingMode` | `QUICK\|STANDARD\|EXTREME` | Trinity processing mode |
| `outputFormat` | `WAV\|FLAC\|MP3` | Export format |
| `ramLimit` | `number` | RAM ceiling % (25–100) |
| `autoLPF/HPF/Vocal` | `string` | Parsed Auto-EQ readouts from logs |
| `inputPreviewUrl` | `string` | `voxis-file://` URL for audio preview |

### Pipeline Step Detection
Regex match on log lines:
```
[1/6] → INGEST    (FFmpeg Universal Decode)
[2/6] → SEPARATE  (BS-RoFormer Voice Isolation)
[3/6] → ANALYZE   (Spectrum + Auto-EQ Profile)
[4/6] → DENOISE   (VoiceRestore Enhancement)
[5/6] → UPSCALE   (AudioSR Diffusion → 48kHz)
[6/6] → MASTER    (Harman Curve Mastering)
Finalizing Export → EXPORT (24-bit Output)
```

Auto-EQ regex: `HPF=(\d+)Hz`, `LPF=(\d+)Hz`, `Vocal=([+-]?[\d.]+)dB`

---

## Layer 3 — Trinity V8.1 Engine
`trinity_engine/trinity_core.py` · `trinity_engine/modules/`

**Binary:** `app/resources/bin/trinity_v8_core` (~638MB, arm64 macOS / x64 Windows)
**Build:** PyInstaller one-file, 67 hidden imports

### CLI Interface
```bash
trinity_v8_core \
  --input  <file>           # Any audio/video format
  --output <file>           # Output path (.wav or .flac)
  --format WAV|FLAC         # Output format (MP3 handled by Electron post-process)
  --stereo-width <0.0–1.0>  # Stereo width (0=mono, 0.5=default, 1.0=wide)
  --extreme                 # Enable EXTREME denoising mode
  --ram-limit <25–100>      # RAM usage ceiling % (next binary rebuild)
```

### Pipeline

```
INPUT (any audio/video)
  │
  ▼
[1/6] INGEST ──────── AudioDecoder (ingest.py)
  │   FFmpeg decode → 44.1kHz stereo WAV
  │   Import buffer: stat-based (size+mtime), skips re-decode of same file
  │
  ▼
[2/6] SEPARATE ─────── GlassStoneSeparator (uvr_processor.py)
  │   BS-RoFormer vocal isolation
  │   Note: fails on <10s audio (model limitation)
  │
  ▼
[3/6] ANALYZE ──────── NoiseProfiler (spectrum_analyzer.py)
  │   Spectral analysis → noise_profile dict
  │   Auto-EQ: HPF (20–80 Hz), LPF (14k–20k Hz), Vocal dB
  │   Emits: HPF=__Hz LPF=__Hz Vocal=__dB  (parsed by UI)
  │
  ▼
[4/6] DENOISE ──────── VoiceRestoreWrapper (voicerestore_wrapper.py)
  │   DeepFilterNet3 pre-diffusion
  │   Output: 24kHz WAV
  │
  ▼
[5/6] UPSCALE ──────── TrinityUpscaler (upsampler.py)
  │   AudioSR latent diffusion → 48kHz
  │   Post-diffusion denoise pass
  │
  ▼
[6/6] MASTER ───────── PedalboardMastering (mastering_phase.py)
  │   Harman Curve EQ:
  │     Bass shelf:    +4.0 dB  @ 105 Hz,  Q=0.7
  │     Mud cleanup:   -1.5 dB  @ 250 Hz,  Q=0.8
  │     Presence:      +1.5 dB  @  3 kHz,  Q=1.0  (+auto_vocal × 0.5)
  │     De-harsh:      -1.0 dB  @ 6.5 kHz, Q=1.5
  │     Treble shelf:  -2.5 dB  @  10 kHz, Q=0.7
  │   Peak normalize → -1 dBFS → gain → limiter
  │
  ▼
EXPORT ─────────────── finalize_export() (ingest.py)
      24-bit WAV or FLAC
      (MP3 @ 320kbps via FFmpeg in Electron post-process)

OUTPUT → ~/Music/Voxis Restored/stem_voxis_mastered.[ext]
```

### Shared Services

| Module | Class | Purpose |
|--------|-------|---------|
| `device_utils.py` | `DeviceOptimizer` | CUDA/MPS/CPU detection, RAM guard, gc.collect() between stages |
| `pipeline_cache.py` | `cache` (singleton) | Import buffer (stat) + stage cache (hash, 8GB LRU, TTL eviction) |
| `retry_engine.py` | `RetryEngine` | `@resilient_stage` decorator — 3 retries, GPU→CPU fallback |
| `error_telemetry.py` | `ErrorTelemetryController` | Structured error logging |

### External ML Libraries (`modules/external/`)
| Library | Purpose |
|---------|---------|
| `audiosr/` | Latent diffusion audio super-resolution (48kHz) |
| `dfn/` | DeepFilterNet3 STFT-domain denoiser |
| `voicerestore/` | Diffusion-based voice restoration (BigVGAN vocoder) |
| `diff_hiervc/` | Hierarchical voice conversion |
| `frame_transformer/` | Frame-level audio transformation |
| `mss_onnx/` | Multi-scale ONNX separator (alt backend) |
| `phase/` | Phase reconstruction |
| `phaselimiter_gui/` | Phase limiter GUI |

---

## Layer 4 — Storage

```
~/Music/Voxis Restored/              ← Final output files
  stem_voxis_mastered.wav
  stem_voxis_mastered_1.wav          ← Collision-safe naming

dependencies/stage_cache/            ← Pipeline stage cache (max 8GB LRU)
  01_ingest_[hash].wav
  02_separate_[hash].wav
  03_analyze_[hash].json
  04_denoise_[hash].wav
  05_upscale_[hash].wav

dependencies/models/                 ← Downloaded ML model weights
  audio_separator/                   BS-RoFormer
  deepfilternet/                     DFN3
  huggingface/                       HuggingFace cache
  voicerestore/                      VoiceRestore checkpoint
```

---

## Distribution

| Platform | Format | Size | Notes |
|----------|--------|------|-------|
| macOS arm64 | DMG | ~742MB | `app/release/Voxis 4.0 DENSE-4.0.0-arm64.dmg` |
| macOS arm64 | Homebrew Cask | — | `brew tap GlassStoneLabs/voxis && brew install --cask voxis` |
| Windows x64 | NSIS | TBD | Bundles ffmpeg.exe + ffprobe.exe |
| All | Auto-update | — | electron-updater → GitHub Releases, manual prompt |

**Requirements:** macOS 12+, arm64 (Apple Silicon) · FFmpeg (macOS, system install)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI Framework | React 19, TypeScript 5.8, Vite 7, Framer Motion 12 |
| Desktop Shell | Electron 35, electron-builder 26, electron-updater 6 |
| Styling | Bauhaus.css (custom design system) |
| ML Pipeline | PyTorch, BS-RoFormer, AudioSR, DeepFilterNet3, VoiceRestore |
| DSP | Pedalboard (Spotify), librosa, soundfile, scipy |
| Audio I/O | FFmpeg (decode/encode), torchaudio |
| Packaging | PyInstaller (one-file binary), DMG, NSIS |
| Distribution | GitHub Releases (GlassStoneLabs/VOXIS), Homebrew Tap |
| Version Control | Git, GitHub |
