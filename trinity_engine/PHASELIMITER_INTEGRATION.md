# PhaseLimiter AI Mastering — Integration Guide
**VOXIS V4.0.0 DENSE · Glass Stone LLC © 2026 · CEO: Gabriel B. Rodriguez**

---

## Overview

Stage 7 (Master) now uses **PhaseLimiter AI** as its primary mastering engine, replacing the standalone Harman EQ + Pedalboard chain. If the binary is unavailable the system transparently falls back to the existing Harman/Pedalboard chain — no configuration needed.

| Engine | Description |
|--------|-------------|
| **PhaseLimiter AI** *(primary)* | AI mastering from bakuage.com/aimastering.com — MS matching, bass preservation, phase-coherent true-peak limiting |
| **Harman/Pedalboard** *(fallback)* | Harman target curve EQ + compressor + LUFS norm + brickwall limiter |

---

## Mode Parameters

PhaseLimiter is active on **every mode**:

| Mode | Mastering Engine | Intensity | Bass | Loudness | Overlap |
|------|-----------------|-----------|------|----------|---------|
| `EXTREME` | `mastering5` | 1.00 | ✅ | −14 LUFS | 0.95 |
| `HIGH` | `mastering5` | 0.80 | ✅ | −14 LUFS | 0.75 |
| `MEDIUM` | `mastering3` | 0.60 | ❌ | −14 LUFS | 0.50 |
| `FAST` | `mastering2` | 0.40 | ❌ | −14 LUFS | 0.25 |

> **Overlap** is the vocal isolation overlap (GS-PRISM, Stage 2) — higher = fewer boundary artifacts.

---

## Stage 7 Pipeline

```
Input WAV (48 kHz, 24-bit)
  │
  ▼
[1] Stereo Width — M/S processing (Pedalboard, always applied)
  │
  ▼
[2] PhaseLimiter AI ──► SUCCESS → mastered WAV (−0.5 dBTP / −14 LUFS)
  │   phase_limiter binary
  │   --mastering true
  │   --mastering_mode mastering5/3/2
  │   --reference -14 (loudness mode)
  │   --ceiling -0.5 (true_peak)
  │   --limiting_mode phase
  │
  └── FAIL / NOT FOUND
         │
         ▼
    [Fallback] Harman EQ → Compressor → LUFS norm → Peak norm → Limiter
```

---

## Binary Location

The wrapper searches in this priority order:

1. `modules/external/phase/bin/Release/phase_limiter` ← **primary (built from source)**
2. `modules/external/phase/bin/phase_limiter` ← cmake Unix/Ninja output
3. `modules/external/phaselimiter_gui/phaselimiter/bin/phase_limiter` ← GUI bundle
4. System `PATH` (`which phase_limiter`)

---

## Building the Binary

### macOS — Native ARM64 (Apple Silicon) ✅ Recommended

Uses **Apple Accelerate (vDSP)** instead of Intel IPP — pure arm64, no Rosetta 2.

```bash
cd trinity_engine/modules/external/phase
./build_macos_native.sh
```

**Requirements** (auto-installed by the script):
- Xcode + Command Line Tools
- Homebrew: `cmake boost libsndfile tbb libpng zlib fftw`

**What the native build does differently:**
- Replaces Intel IPP DFT/FFT with Apple `vDSP_DFT_Execute` / `vDSP_fft_zrip`
- Implements IPP types and API surface via `deps/bakuage/include/ipp_apple_stub.h`
- Compiles with `-march=native -mcpu=native` for full Apple Silicon NEON/AMX
- Links `-framework Accelerate` (zero extra installs)

---

### macOS — x86_64 via Rosetta 2

For Intel Macs or when you need the original Intel-optimized binary on Apple Silicon.

```bash
cd trinity_engine/modules/external/phase
./build_macos.sh
```

**Additional requirements:**
- Intel oneAPI Base Toolkit (IPP): https://www.intel.com/content/www/us/en/developer/tools/oneapi/base-toolkit-download.html
- Miniforge / Conda (for TBB) — installed automatically if missing

---

### Windows — x64 (PowerShell)

```powershell
cd trinity_engine\modules\external\phase
.\build_windows.ps1 -BoostRoot "C:\local\boost" -SndFileDir "C:\local\libsndfile"
```

**Requirements:**
- Visual Studio 2019 or 2022 (Desktop C++ workload)
- Intel oneAPI Base Toolkit (IPP)
- Boost for MSVC (prebuilt or vcpkg)
- libsndfile (prebuilt)

Custom paths:
```powershell
.\build_windows.ps1 `
    -VisualStudioVersion "Visual Studio 16 2019" `
    -BoostRoot "C:\tools\boost_1_82_0" `
    -SndFileDir "C:\tools\libsndfile"
```

---

## Apple Accelerate IPP Stub

**File:** `deps/bakuage/include/ipp_apple_stub.h`

Provides a complete IPP API surface backed by Apple Accelerate:

| IPP Function | Apple Accelerate Replacement |
|---|---|
| `ippsDFTGetSize_R_32f` / `ippsDFTInit_R_32f` | `vDSP_DFT_zop_CreateSetup` |
| `ippsDFTFwd_RToCCS_32f` / `RToPerm_32f` / `RToPack_32f` | `vDSP_DFT_Execute` + format conversion |
| `ippsDFTInv_CCSToR_32f` / `PermToR_32f` / `PackToR_32f` | `vDSP_DFT_Execute` (inverse) + 1/N scaling |
| `ippsFFTGetSize_R_32f` / `ippsFFTInit_R_32f` | `vDSP_create_fftsetup` |
| `ippsFFTFwd_RToCCS_32f` / `RToPerm_32f` / `RToPack_32f` | `vDSP_fft_zrip` + format conversion |
| `ippsFFTInv_*` | `vDSP_fft_zrip` (inverse) + 1/N scaling |
| `ippsMalloc_8u` / `ippsFree` | `std::malloc` / `std::free` |
| `ippsSet_64f` | scalar loop |
| `ippsWinKaiser_64f_I` | `std::cyl_bessel_i` (C++17) |

Output formats — CCS, Pack, and Perm — are fully implemented with correct DC/Nyquist placement.

---

## Files Changed / Added

| File | Change |
|------|--------|
| `modules/phaselimiter_wrapper.py` | **NEW** — subprocess wrapper, binary finder, mode→param mapping |
| `modules/mastering_phase.py` | Stage 7 now tries PhaseLimiter first, Harman fallback |
| `trinity_core.py` | Passes `mode=` to `PedalboardMastering`, `GlassStoneSeparator` |
| `modules/uvr_processor.py` | Per-mode overlap (`_MODE_OVERLAP`) for vocal isolation |
| `modules/external/phase/build_macos_native.sh` | **NEW** — ARM64 native build |
| `modules/external/phase/build_macos.sh` | **NEW** — x86_64 / Rosetta 2 build |
| `modules/external/phase/build_windows.ps1` | **NEW** — Windows x64 PowerShell build |
| `modules/external/phase/deps/bakuage/include/ipp_apple_stub.h` | **NEW** — Apple Accelerate IPP stub |

---

## Troubleshooting

### "PhaseLimiter Binary not found — Harman/Pedalboard chain will be used as fallback."
The binary hasn't been built yet. Run the appropriate build script above.

### Build fails: `boost_system not found`
Homebrew Boost 1.69+ made `boost_system` header-only. The native build script uses `-DBoost_NO_BOOST_CMAKE=ON` and links only the components that have `.a` files. If it still fails:
```bash
brew reinstall boost
```

### Build fails: `Intel IPP not found`
Only relevant to `build_macos.sh` (Rosetta path). Use `build_macos_native.sh` instead — it has zero Intel IPP dependency.

### Binary crashes on Apple Silicon
Ensure you used `build_macos_native.sh` (arm64) not `build_macos.sh` (x86_64 Rosetta). Check with:
```bash
lipo -info trinity_engine/modules/external/phase/bin/Release/phase_limiter
```
Should show `arm64`, not `x86_64`.

---

*PhaseLimiter source: https://github.com/ai-mastering/phaselimiter-gui*
*Algorithm: bakuage.com / aimastering.com (MIT License)*
