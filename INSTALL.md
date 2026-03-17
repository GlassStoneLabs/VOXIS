# VOXIS 4.0 DENSE — Installation Guide

**Professional Audio Restoration · Trinity V8.1 Engine**
Copyright © 2026 Glass Stone LLC · CEO: Gabriel B. Rodriguez

---

## System Requirements

| Requirement | Minimum |
|---|---|
| **OS** | macOS 12 Monterey or later |
| **Architecture** | Apple Silicon (M1 / M2 / M3 / M4) |
| **RAM** | 8 GB (16 GB recommended) |
| **Disk** | 2 GB free space |
| **Dependencies** | FFmpeg (installed automatically via Homebrew) |

---

## Installation Methods

### Method 1 — Homebrew (Recommended)

The fastest way to install Voxis. Requires [Homebrew](https://brew.sh).

```bash
brew tap GlassStoneLabs/voxis
brew install --cask voxis
```

This installs **Voxis.app** to `/Applications` and creates the output folder at `~/Music/Voxis Restored/`.

To update to a newer version:

```bash
brew upgrade --cask voxis
```

To uninstall:

```bash
brew uninstall --cask voxis
```

---

### Method 2 — One-Line Installer

No Homebrew? Run this in Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/GlassStoneLabs/VOXIS/main/install.sh | bash
```

This will:
1. Download the latest DMG from GitHub Releases
2. Mount and copy **Voxis.app** to `/Applications`
3. Create `~/Music/Voxis Restored/`
4. Clean up temporary files

---

### Method 3 — Manual DMG Install

1. Download the latest DMG from [GitHub Releases](https://github.com/GlassStoneLabs/VOXIS/releases)
2. Open `Voxis-4.0.0-arm64.dmg`
3. Drag **Voxis** to your Applications folder
4. Eject the DMG

---

## First Launch

On first launch, macOS may show a security prompt:

> "Voxis" can't be opened because Apple cannot check it for malicious software.

To resolve this:

1. Open **System Settings → Privacy & Security**
2. Scroll to the **Security** section
3. Click **"Open Anyway"** next to the Voxis message
4. Alternatively, run in Terminal:
   ```bash
   xattr -cr "/Applications/Voxis.app"
   ```

---

## FFmpeg Dependency

Voxis requires FFmpeg for audio/video ingestion. If not already installed:

```bash
# Via Homebrew (recommended)
brew install ffmpeg

# Verify installation
ffmpeg -version
```

---

## Pipeline Overview

Voxis processes audio through 6 stages:

```
[1/6] INGEST      FFmpeg decode → 44.1kHz stereo WAV
[2/6] SEPARATE    BS-RoFormer voice isolation
[3/6] ANALYZE     Spectrum profiling + Auto-EQ parameters
[4/6] DENOISE     VoiceRestore enhancement (BigVGAN 24kHz)
[5/6] UPSCALE     AudioSR diffusion upsampling → 48kHz
[6/6] MASTER      Harman curve EQ + normalization + limiter
```

### Harman Target Curve (Mastering)

The final mastering stage applies a psychoacoustically-optimized EQ based on research by Sean Olive et al. (2013–2018):

| Band | Gain | Frequency | Q |
|---|---|---|---|
| Bass Shelf | +4.0 dB | 105 Hz | 0.7 |
| Mud Cleanup | −1.5 dB | 250 Hz | 0.8 |
| Presence | +1.5 dB | 3 kHz | 1.0 |
| De-harsh | −1.0 dB | 6.5 kHz | 1.5 |
| Treble Shelf | −2.5 dB | 10 kHz | 0.7 |

---

## Output

All restored files are saved to:

```
~/Music/Voxis Restored/
```

File naming convention: `{original_name}_voxis_mastered.wav` (or `.flac`)

---

## Supported Input Formats

| Audio | Video (audio extracted) |
|---|---|
| WAV, MP3, FLAC, AAC, OGG, WMA, AIFF, M4A | MP4, MOV, MKV, AVI, WebM |

---

## Development Setup

For contributors and developers:

```bash
# Clone the repository
git clone https://github.com/GlassStoneLabs/VOXIS.git
cd VOXIS

# Install Node dependencies
cd app && npm install

# Run in development mode (hot-reload)
npm run electron:dev

# Build DMG installer
npm run electron:build
```

### Rebuilding the Engine Binary

```bash
# Install Python dependencies
pip install setuptools==69.5.1 "numpy<2.0"
pip install -r requirements.txt

# Build frozen binary
pyinstaller trinity_v8_core.spec --noconfirm

# Deploy to app resources
cp dist/trinity_v8_core app/resources/bin/
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| "App can't be opened" | Run `xattr -cr "/Applications/Voxis.app"` |
| FFmpeg not found | Install with `brew install ffmpeg` |
| Pipeline stalls at SEPARATE | Ensure 8GB+ RAM is available; BS-RoFormer is memory-intensive |
| Silent output | Check that input file is longer than 10 seconds (BS-RoFormer limitation) |
| No output folder | Manually create `~/Music/Voxis Restored/` |

---

## Architecture

See the full technical diagram: [`docs/architecture.svg`](docs/architecture.svg)

---

**Built by Glass Stone LLC · Powered by Trinity V8.1**
