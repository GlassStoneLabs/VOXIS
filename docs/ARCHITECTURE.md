# VOXIS V4.0.0 DENSE — System Architecture
**Glass Stone LLC © 2026 | Powered by Trinity V8.2**

---

## Overview

VOXIS is a professional voice restoration desktop application built on a three-layer Tauri 2.0 stack. All audio processing runs fully local — no API calls, no cloud upload, no network dependency.

1. **Tauri 2.0 Frontend** — Native WebView shell, React/TypeScript UI, zero-copy file-path IPC
2. **Rust Core** — Sidecar lifecycle manager, file I/O orchestration, Tauri event emitter
3. **Trinity V8.2 Engine** — Python ML pipeline frozen into a portable PyInstaller binary, served via FastAPI sidecar

---

## Tauri vs. Electron — Estimated Performance Improvement

Migrating from Electron 35 to Tauri 2.0 targets the following gains. Figures are estimates based on published Tauri benchmarks and the IPC architecture decision documented in the whitepaper.

| Metric | Electron (prior) | Tauri 2.0 (target) | Estimated Improvement |
|--------|-----------------|--------------------|-----------------------|
| Idle RAM footprint | 150–300 MB baseline | 30–50 MB | **~80% reduction** |
| Installer size (macOS DMG) | 80–244 MB | 2.5–10 MB | **~24× smaller** |
| Cold-start time | ~2–4 s | Sub-500 ms | **~4–8× faster** |
| IPC latency — file-path (macOS) | ~5 ms (10 MB buffer) | <1 ms (string only) | **>5× faster** |
| IPC latency — file-path (Windows) | ~200 ms (10 MB buffer) | <1 ms (string only) | **>200× faster** |
| Node.js runtime overhead | Bundled Chromium + Node (~80 MB) | Native WebView, no Node | **Eliminated** |
| Binary signing surface | Full Chromium fork | OS-native WebView | **Reduced attack surface** |

> **IPC design decision:** Raw audio buffer transfer via Tauri IPC was benchmarked at ~200 ms for 10 MB on Windows — rejected. File-path string passing via HTTP POST to localhost achieves <1 ms on both platforms and is the chosen architecture.

---

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    VOXIS V4.0.0 DENSE                           │
│                   Glass Stone LLC © 2026                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LAYER 1 — TAURI 2.0 FRONTEND                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  React 19 · TypeScript 5.8 · Vite · Bauhaus.css         │    │
│  │  Native WebView (WKWebView / WebView2)                  │    │
│  │  Drag-drop → file path string only (never audio buffer) │    │
│  │  convertFileSrc() → local audio preview                 │    │
│  └────────────────────┬────────────────────────────────────┘    │
│                       │ invoke() / Tauri events                  │
│  LAYER 2 — RUST CORE  ▼                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Tauri sidecar manager · File I/O · Process orchestrator│    │
│  │  Spawns / monitors / auto-restarts Python sidecar       │    │
│  │  Forwards file path via HTTP POST → localhost:PORT      │    │
│  │  Emits progress events → frontend event bus             │    │
│  └────────────────────┬────────────────────────────────────┘    │
│                       │ HTTP POST (file path string)             │
│  LAYER 3 — TRINITY V8.2 ENGINE  ▼                               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  FastAPI sidecar · PyInstaller one-file binary           │    │
│  │  ONNX Runtime: CoreML EP (macOS) · CUDA EP (Windows)    │    │
│  │  DirectML fallback (AMD / Intel iGPU)                   │    │
│  │  ~5 GB model load footprint · ~500 MB ONNX on disk      │    │
│  │  FFmpeg static build bundled                            │    │
│  └────────────────────┬────────────────────────────────────┘    │
│                       │ output file path returned                │
│  LAYER 4 — STORAGE    ▼                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ~/Music/Voxis Restored/  ← Final output files          │    │
│  │  dependencies/stage_cache/ ← 8 GB LRU pipeline cache    │    │
│  │  dependencies/models/      ← ML model weights           │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## IPC & Runtime Flow Diagram

```
USER ACTION
  │
  │  drag-drop or file open
  ▼
┌─────────────────────┐
│   TAURI FRONTEND    │  captures OS file path string only
│   (React / WebView) │  never touches raw audio buffer
└──────────┬──────────┘
           │ invoke("run_trinity", { path })
           ▼
┌─────────────────────┐
│     RUST CORE       │  validates path, checks sidecar health
│  (Tauri commands)   │  platform detection via target-triple:
└──────────┬──────────┘  aarch64-apple-darwin / x86_64-pc-windows-msvc
           │ HTTP POST → localhost:PORT  { "input": "/path/to/file" }
           ▼
┌─────────────────────┐
│  TRINITY V8.2       │  reads audio from disk (not from memory)
│  PYTHON SIDECAR     │  runs 6-stage pipeline
│  (FastAPI server)   │  writes output → /tmp/voxis_out/
└──────────┬──────────┘
           │ HTTP 200 → { "output": "/tmp/voxis_out/stem_mastered.wav" }
           ▼
┌─────────────────────┐
│     RUST CORE       │  receives output path
│  (Tauri commands)   │  emits Tauri event → frontend
└──────────┬──────────┘
           │ Tauri event: "trinity-done" { outputPath }
           ▼
┌─────────────────────┐
│   TAURI FRONTEND    │  convertFileSrc(outputPath) → local audio preview
│   (React / WebView) │  displays completion overlay + export options
└─────────────────────┘

IPC Latency Comparison (file-path string, 10 MB audio):
  macOS:   <1 ms  ✓  (was ~5 ms raw buffer via Tauri IPC)
  Windows: <1 ms  ✓  (was ~200 ms raw buffer via Tauri IPC)
```

---

## Layer 1 — Tauri 2.0 Frontend
`src/App.tsx` · `src/Bauhaus.css`

**Stack:** Tauri 2.0 · React 19 · TypeScript 5.8 · Vite · Framer Motion · Bauhaus.css

### UI Layout
```
┌─ Header ─────────────────────────────────────────┐
│  [Bauhaus Logo]  VOXIS DENSE  BY GLASS STONE  ●  │
├─ Sidebar (210px) ─┬─ Main Panel ─────────────────┤
│  Processing Mode  │  File Strip + Audio Preview   │
│  Upscale Factor   │  Status + EQ Readout Chips    │
│  Output Format    │  Pipeline Steps (6 stages)    │
│  Denoise Strength │  Progress Bar + Elapsed Time  │
│  Noise Profile    │  Log Viewer (200 line buffer) │
│  Restoration Steps│  Action Bar                   │
│  Generation Guide │                               │
│  High Precision   │  [Completion Overlay]         │
│  Stereo Output    │   ✓ VOICE RESTORED            │
│  RAM Limit        │   Export / Reveal / New       │
└───────────────────┴───────────────────────────────┘
```

**Typography:** Geist Sans (UI labels) · Space Grotesk (headers) · Geist Mono (numeric readouts)

### Key State
| State | Type | Purpose |
|-------|------|---------|
| `status` | `idle\|running\|done\|error` | Pipeline lifecycle |
| `currentStep` | `number` | Active pipeline step (1–6) |
| `logs` | `string[]` | Engine stdout/stderr (200 line buffer) |
| `processingMode` | `QUICK\|STANDARD\|EXTREME` | Trinity processing mode |
| `outputFormat` | `WAV\|FLAC\|MP3` | Export format |
| `ramLimit` | `number` | RAM ceiling % (25–100) |
| `autoLPF/HPF/Vocal` | `string` | Parsed Auto-EQ readouts from logs |
| `inputPreviewUrl` | `string` | `convertFileSrc()` URL for local audio preview |

### Tauri Commands (replaces Electron IPC)
| Command | Direction | Description |
|---------|-----------|-------------|
| `dialog_open_file` | invoke | Native open-file dialog (voice & audio filters) |
| `dialog_save_file` | invoke | Native save-as dialog |
| `trinity_run_engine` | invoke | Dispatch to Python sidecar via HTTP POST |
| `trinity_cancel_engine` | invoke | SIGTERM active sidecar process |
| `trinity_get_version` | invoke | Return Trinity version string |
| `shell_open_path` | invoke | Reveal file in Finder/Explorer |
| `shell_open_file` | invoke | Open file in default app |
| `file_copy` | invoke | Async file copy (Save As) |
| `update_download` | invoke | Trigger Tauri updater download |
| `update_install` | invoke | Quit and install update |
| `trinity-log` | event → frontend | Stream engine stdout/stderr line-by-line |
| `trinity-done` | event → frontend | Engine completed, emit output path |
| `update-status` | event → frontend | Update availability/progress/downloaded |

### Frontend API Bridge
```typescript
// Tauri invoke() replaces window.electronAPI context bridge
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { convertFileSrc } from "@tauri-apps/api/core";

// File preview — no buffer transfer
const previewUrl = convertFileSrc(localFilePath);

// Run pipeline — passes file path string only
await invoke("trinity_run_engine", { inputPath, options });

// Stream logs
const unlisten = await listen("trinity-log", (event) => {
  appendLog(event.payload as string);
});
```

### Pipeline Step Detection
Regex match on log lines:
```
[1/6] → INGEST    (FFmpeg Universal Decode)
[2/6] → SEPARATE  (Mel-Band RoFormer Voice Isolation)
[3/6] → ANALYZE   (Conv1d-STFT Spectrum Analysis)
[4/6] → DENOISE   (MP-SENet / DeepFilterNet3)
[5/6] → UPSCALE   (HiFi-SR 48 → 96 kHz)
[6/6] → MASTER    (ITU-R BS.1770-4 Loudness + TPDF)
Finalizing Export → EXPORT (24-bit Output)
```

Auto-EQ regex: `HPF=(\d+)Hz`, `LPF=(\d+)Hz`, `Vocal=([+-]?[\d.]+)dB`

---

## Layer 2 — Rust Core
`src-tauri/src/main.rs` · `src-tauri/src/commands/`

### Responsibilities
- Manages Python ML sidecar lifecycle — spawns, monitors, auto-restarts on fault
- File-path passing via HTTP POST to `localhost:PORT` — avoids WebView2 IPC bottleneck (200 ms / 10 MB on Windows)
- Platform detection via Tauri target-triple binary naming:
  - `aarch64-apple-darwin` (macOS Apple Silicon)
  - `x86_64-pc-windows-msvc` (Windows x64)
- Idle RAM footprint: **30–50 MB** vs. Electron 150–300 MB baseline
- Monitors sidecar health; exposes progress events to frontend via Tauri event emitter

### Sidecar Binary Naming
```
resources/
  trinity_v8_core-aarch64-apple-darwin      ← macOS arm64
  trinity_v8_core-x86_64-pc-windows-msvc   ← Windows x64
```

---

## Layer 3 — Trinity V8.2 Engine
`trinity_engine/trinity_core.py` · `trinity_engine/modules/`

**Binary:** `resources/trinity_v8_core-[target-triple]` (~638 MB, arm64 macOS / x64 Windows)
**Build:** PyInstaller one-file, served via FastAPI · ONNX Runtime unified

### CLI / HTTP Interface
```bash
# Invoked by Rust core via HTTP POST to localhost sidecar
POST /run
{
  "input":        "<file>",          # Any audio/video format
  "output":       "<file>",          # Output path (.wav or .flac)
  "format":       "WAV|FLAC",        # MP3 handled by FFmpeg post-process
  "stereo_width": 0.0–1.0,           # Stereo width (0=mono, 0.5=default, 1.0=wide)
  "extreme":      true|false,        # Enable EXTREME denoising mode
  "ram_limit":    25–100             # RAM usage ceiling %
}
```

### Trinity V8.2 Pipeline

```
INPUT (any audio/video)
  │
  ▼
[1/6] INGEST ─────────── AudioDecoder (ingest.py)
  │   FFmpeg static build → 48 kHz / 32-bit float / mono
  │   Formats: WAV · MP3 · FLAC · AAC · OGG · MP4 · MOV · MKV
  │   libsoxr bandlimited sinc resampling (highest quality)
  │   Import buffer: stat-based (size+mtime), skips re-decode of same file
  │
  ▼
[2/6] SEPARATE ────────── Mel-Band RoFormer (uvr_processor.py)
  │   ONNX via python-audio-sep — no direct PyTorch dependency at runtime
  │   Primary: Mel-Band RoFormer  · 12.97 dB SDR (MVSep leaderboard Feb 2026)
  │   Fast mode: SCNet 10.08M params · 9.0 dB SDR · 48% CPU vs. primary
  │   Note: fails on <10s audio (model limitation)
  │   ONNX export: CPU device only — MPS export corrupts BatchNorm+Conv2d (#83230)
  │
  ▼
[3/6] ANALYZE ─────────── nnAudio Conv1d-STFT (spectrum_analyzer.py)
  │   DFT expressed as 1D convolution — bypasses PyTorch MPS FFT bugs
  │   #120237 & #126649 (torch.fft.rfft / torch.fft.irfft catastrophic on MPS)
  │   Full GPU acceleration maintained via Conv1d on MPS — no CPU fallback required
  │   Auto-EQ: HPF (20–80 Hz), LPF (14k–20k Hz), Vocal dB
  │   Emits: HPF=__Hz LPF=__Hz Vocal=__dB  (parsed by UI)
  │
  ▼
[4/6] DENOISE ─────────── MP-SENet / DeepFilterNet3 (voicerestore_wrapper.py)
  │   Quality mode: MP-SENet · PESQ 3.60 · VoiceBank+DEMAND · 2.26M params
  │   Parallel magnitude-mask and phase decoders — anti-wrapping phase loss
  │   Real-time mode: DeepFilterNet3 (Rust native ARM64) · PESQ 3.17 · RTF 0.19
  │   Alt: DPDFNet (dual-path RNN) · PESQ 3.38 — evaluated for v4.1 inclusion
  │   Output: 32-bit float / 48 kHz
  │
  ▼
[5/6] UPSCALE ─────────── HiFi-SR via ClearerVoice-Studio (upsampler.py)
  │   Unified transformer-convolutional GAN · 48 → 96 kHz single pass
  │   Eliminates vocoder step required by diffusion-based approaches (~25 DDIM steps)
  │   LSD 0.82 on VCTK — best among all benchmarked models incl. FlashSR (1-step DDPM)
  │   96 kHz output — no competitor in ML audio restoration targets this sample rate
  │
  ▼
[6/6] MASTER ──────────── Phase Limiter + Loudness (mastering_phase.py)
  │   True peak limiting per ITU-R BS.1770-4 · ceiling: −1.0 dBTP
  │   Loudness normalization: −14 LUFS default (Spotify/YouTube)
  │                           −23 LUFS EBU R128 broadcast preset
  │   64-bit accumulator at mastering · ~144 dB internal SNR
  │   TPDF dither applied exactly once — at final bit-depth reduction only
  │   Never mid-chain (accumulates noise; 32-bit chain keeps quant. error < 24-bit floor)
  │
  ▼
EXPORT ─────────────────── finalize_export() (ingest.py)
      WAV 24-bit (TPDF + noise shaping from 32-bit master)
      FLAC lossless (no dither required — codec handles quantization)
      MP3/AAC @ 320kbps via FFmpeg post-process (codec handles quantization)

OUTPUT → ~/Music/Voxis Restored/stem_voxis_mastered.[ext]
```

### Signal Precision Flow
```
SOURCE      STAGE 01      STAGES 02–04   STAGE 05       STAGE 06      EXPORT
INPUT       INGEST        PROCESSING     SUPER-RES      MASTER        OUTPUT

Variable ─► 48 kHz ──────► 48 kHz ──────► 96 kHz ──────► 96 kHz ────► 24-bit
            32-bit float   32-bit float   32-bit float   64-bit acc.   WAV / FLAC
            Mono           Conv1d STFT    HiFi-SR GAN    BS.1770-4     TPDF dither
```

IEEE 754 32-bit float throughout · 64-bit accumulators at mastering · ~144 dB internal SNR

### Shared Services

| Module | Class | Purpose |
|--------|-------|---------|
| `device_utils.py` | `DeviceOptimizer` | CUDA/MPS/CPU detection, RAM guard, gc.collect() between stages |
| `pipeline_cache.py` | `cache` (singleton) | Import buffer (stat) + stage cache (hash, 8 GB LRU, TTL eviction) |
| `retry_engine.py` | `RetryEngine` | `@resilient_stage` decorator — 3 retries, GPU→CPU fallback |
| `error_telemetry.py` | `ErrorTelemetryController` | Structured error logging |

### External ML Libraries (`modules/external/`)
| Library | Purpose | Backend |
|---------|---------|---------|
| `audiosr/` (replaced by HiFi-SR) | Legacy diffusion SR — superseded | — |
| `dfn/` | DeepFilterNet3 STFT-domain denoiser | Rust native ARM64 |
| `voicerestore/` | Flow-matching transformer (301M params) | ONNX / PyTorch |
| `mss_onnx/` | Mel-Band RoFormer separator | ONNX (CPU device only) |
| `hifi_sr/` | ClearerVoice-Studio GAN super-resolution | ONNX Runtime |
| `mp_senet/` | MP-SENet quality denoiser | ONNX Runtime |

### ONNX Runtime Execution Providers
| Platform | Primary EP | Fallback |
|----------|-----------|----------|
| macOS Apple Silicon | CoreML EP (CPU + GPU + Neural Engine) | CPU |
| Windows NVIDIA | CUDA EP (RTX 30xx+, 8 GB VRAM min.) | DirectML |
| Windows AMD / Intel | DirectML | CPU |

---

## Layer 4 — Storage

```
~/Music/Voxis Restored/              ← Final output files
  stem_voxis_mastered.wav
  stem_voxis_mastered_1.wav          ← Collision-safe naming

dependencies/stage_cache/            ← Pipeline stage cache (max 8 GB LRU)
  01_ingest_[hash].wav
  02_separate_[hash].wav
  03_analyze_[hash].json
  04_denoise_[hash].wav
  05_upscale_[hash].wav

dependencies/models/                 ← Downloaded ML model weights (~5 GB total)
  audio_separator/                   Mel-Band RoFormer (ONNX)
  deepfilternet/                     DFN3 (Rust native ARM64)
  huggingface/                       HuggingFace cache
  voicerestore/                      VoiceRestore 301M checkpoint
  hifi_sr/                           ClearerVoice-Studio ONNX
  mp_senet/                          MP-SENet 2.26M ONNX
```

---

## Distribution

| Platform | Format | Size | Notes |
|----------|--------|------|-------|
| macOS arm64 | DMG | **2.5–10 MB** | Tauri installer (was 80–244 MB Electron DMG) |
| macOS arm64 | Homebrew Cask | — | `brew tap GlassStoneLabs/voxis && brew install --cask voxis` |
| Windows x64 | NSIS / MSI | TBD | Bundles FFmpeg static build; CUDA EP runtime |
| All | Auto-update | — | Tauri updater → GitHub Releases, manual prompt |

**Requirements:** macOS 12 Monterey+, Apple Silicon (arm64) · Windows 10/11 x86-64 · NVIDIA RTX 30xx+ (Windows GPU acceleration)

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI Framework | React 19, TypeScript 5.8, Vite, Framer Motion, Bauhaus.css |
| Desktop Shell | **Tauri 2.0**, tauri-build, Tauri updater (replaces Electron 35 + electron-builder) |
| IPC | Tauri invoke() commands + event emitter · HTTP POST to localhost (file-path only) |
| Rust Core | Rust (sidecar manager, file I/O, process orchestration) |
| Styling | Bauhaus.css · Geist Sans / Space Grotesk / Geist Mono |
| ML Pipeline | ONNX Runtime (CoreML EP / CUDA EP / DirectML), Mel-Band RoFormer, HiFi-SR, MP-SENet, DeepFilterNet3, VoiceRestore |
| DSP | Pedalboard (Spotify), librosa, soundfile, scipy, nnAudio Conv1d-STFT |
| Audio I/O | FFmpeg static build (decode/encode), torchaudio |
| Packaging | PyInstaller (one-file sidecar binary), Tauri DMG / NSIS |
| Distribution | GitHub Releases (GlassStoneLabs/VOXIS), Homebrew Tap |
| Version Control | Git, GitHub |

---

## Performance Summary — Tauri 2.0 vs. Electron (Estimated)

```
MEMORY
  Electron baseline:  ████████████████████████████████  150–300 MB
  Tauri 2.0 target:   ████████                           30–50 MB
                      ↑ ~80% idle RAM reduction

INSTALLER SIZE
  Electron DMG:       ████████████████████████  80–244 MB
  Tauri DMG:          █                          2.5–10 MB
                      ↑ ~24× smaller distribution

COLD-START
  Electron:           ████████  2–4 s
  Tauri 2.0:          █        <500 ms
                      ↑ ~4–8× faster launch

IPC LATENCY (Windows, 10 MB payload)
  Electron IPC:       ████████████████████████████  ~200 ms (raw buffer)
  Tauri file-path:    ▌                              <1 ms  (string only)
                      ↑ >200× faster on Windows
```

> All Tauri figures are estimates based on published Tauri 2.0 benchmarks and architectural analysis.
> Trinity V8.2 engine performance (12.97 dB SDR, PESQ 3.60, LSD 0.82) is unchanged from V8.1 —
> all ML benchmark scores remain peer-reviewed and independently validated.
