# VOXIS 4.0 DENSE

**Powered by Trinity V8.1 | Built by Glass Stone LLC**
**CEO: Gabriel B. Rodriguez | © 2026**

This desktop application for audio restoration and enhancement is powered by Trinity V8.1 and built by Glass Stone LLC. It transforms degraded, low-quality audio into clean, high-resolution stereo output through a multi-stage AI pipeline.

The application follows strict Bauhaus UI principles, emphasizing form follows function, a primary palette, a geometric grid, and minimal ornamentation.

—

## The Trinity V8.1 Pipeline

The Trinity V8.1 pipeline consists of several steps, each utilizing specific modules and technologies:

| Step | Module | Technology |
|———|————|——————|
| 1 | **Ingest** | FFmpeg universal decoder (WAV, MP3, MP4, MOV, MKV) |
| 2 | **Separate** | Glass Stone Separator — BS-RoFormer vocal extraction |
| 3 | **Analyze** | Spectrum & RMS noise profiling with Auto-EQ detection |
| 4 | **Denoise** | DeepFilterNet3 — HIGH (48dB) or EXTREME (100dB) |
| 5 | **Upscale** | AudioSR latent diffusion → 48kHz stereo |
| 6 | **Master** | Phase Limiter + Stereo Width (Pedalboard) |
| 7 | **Export** | 24-bit WAV or FLAC |

—

## Installing on a New Device

### Option A — DMG Installer (End Users, macOS)

1. Download the `Voxis 4.0 DENSE-4.0.0-arm64.dmg` file from the [Releases](../../releases) page.
2. Open the DMG file and drag the **Voxis 4.0 DENSE** application to the `/Applications` folder.
3. On the first launch, right-click on the application and select **Open** (this bypasses Gatekeeper on the first run).
### Option B — Build from Source (Developers, macOS)

#### 1. System Prerequisites

```bash
# Install Homebrew (if not installed)
/bin/bash -c “$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)”

# Install required system tools
brew install python@3.11 node ffmpeg git

# Verify
```
