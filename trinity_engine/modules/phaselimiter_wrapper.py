# VOXIS V4.0.0 DENSE — PHASELIMITER INTEGRATION
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Wraps the phase_limiter CLI binary (ai-mastering/phaselimiter-gui)
# as a drop-in mastering stage replacing the Harman EQ + compressor +
# LUFS + limiter chain.
#
# Binary args sourced from:
#   modules/external/phaselimiter_gui/mastering.go
#
# CLI invocation:
#   phase_limiter
#     --input <path>
#     --output <path>
#     --ffmpeg <ffmpeg>
#     --mastering true
#     --mastering_mode mastering5
#     --sound_quality2_cache <resource/sound_quality2_cache>
#     --mastering_matching_level <0-1>
#     --mastering_ms_matching_level <0-1>
#     --mastering5_mastering_level <0-1>
#     --erb_eval_func_weighting <true|false>
#     --reference <loudness_db>

import os
import re
import shutil
import subprocess
import platform as _platform

from .path_utils import get_engine_base_dir

# ── Per-mode mastering parameters ────────────────────────────────────────────
# level     : mastering intensity 0.0–1.0   (matching + mastering5 level)
# loudness  : target reference level in dB  (loudness mode, streaming = -14)
# bass      : erb_eval_func_weighting       (bass preservation toggle)
# mode      : phaselimiter mastering_mode

_MODE_PARAMS = {
    "EXTREME": {"level": 1.00, "loudness": -14.0, "bass": True,  "mode": "mastering5"},
    "HIGH":    {"level": 0.80, "loudness": -14.0, "bass": True,  "mode": "mastering5"},
    "MEDIUM":  {"level": 0.60, "loudness": -14.0, "bass": False, "mode": "mastering3"},
    "FAST":    {"level": 0.40, "loudness": -14.0, "bass": False, "mode": "mastering2"},
}

# Candidate binary names in priority order (macOS/Linux first, Windows last)
_BINARY_NAMES = ["phase_limiter", "phase_limiter.exe"]

# Candidate resource dir names
_RESOURCE_DIR = "sound_quality2_cache"


def _fmt_float(x: float) -> str:
    return f"{x:.7f}"


def _fmt_bool(x: bool) -> str:
    return "true" if x else "false"


def find_phase_limiter_binary() -> tuple[str | None, str | None]:
    """
    Locate the phase_limiter executable and its companion sound_quality2_cache.

    The binary is downloaded/built automatically by model_downloader.py on
    first install and placed at the canonical path:

      <engine_base>/modules/external/phase/bin/Release/phase_limiter

    Search order:
      1. Canonical install path (model_registry.get_phaselimiter_binary_path)
      2. cmake Unix Makefiles / Ninja build output
      3. phaselimiter-gui bundled binary
      4. System PATH (shutil.which)

    Returns:
        (binary_path, cache_path) — either may be None if not found.
    """
    base = get_engine_base_dir()
    phase_root = os.path.join(base, "modules", "external", "phase")

    # Hard-coded resource path (always the same regardless of build type)
    cache_path = os.path.join(phase_root, "resource", _RESOURCE_DIR)
    cache = cache_path if os.path.isdir(cache_path) else None

    # Binary name varies by OS
    bin_name = "phase_limiter.exe" if _platform.system() == "Windows" else "phase_limiter"

    # ── Primary: canonical install path (model registry) ─────────────────────
    canonical = os.path.join(phase_root, "bin", "Release", bin_name)
    if os.path.isfile(canonical) and os.access(canonical, os.X_OK):
        return canonical, cache

    # ── Secondary: cmake Unix Makefiles / Ninja build output ────────────────
    unix_bin = os.path.join(phase_root, "bin", bin_name)
    if os.path.isfile(unix_bin) and os.access(unix_bin, os.X_OK):
        return unix_bin, cache

    # ── Tertiary: phaselimiter-gui bundled binary ────────────────────────────
    gui_bin_dir = os.path.join(
        base, "modules", "external", "phaselimiter_gui", "phaselimiter", "bin"
    )
    for name in _BINARY_NAMES:
        full = os.path.join(gui_bin_dir, name)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return full, cache

    # ── Fallback: system PATH ────────────────────────────────────────────────
    for name in _BINARY_NAMES:
        found = shutil.which(name)
        if found:
            return found, cache

    return None, None


class PhaseLimiterWrapper:
    """
    Subprocess wrapper around the phase_limiter CLI binary.

    Replaces the Harman EQ + compressor + LUFS + brickwall limiter chain
    with the AI-mastering algorithm from bakuage.com / aimastering.com.

    Usage
    -----
    wrapper = PhaseLimiterWrapper(mode="HIGH")
    if wrapper.available:
        out = wrapper.process(input_wav, output_path)
    """

    def __init__(self, mode: str = "HIGH"):
        self._mode = mode.upper()
        self._params = _MODE_PARAMS.get(self._mode, _MODE_PARAMS["HIGH"])
        self._binary, self._cache = find_phase_limiter_binary()
        self.available = self._binary is not None
        if self.available:
            print(f"[PhaseLimiter] Binary: {self._binary}")
            print(f"[PhaseLimiter] Cache:  {self._cache or '(none — quality preset will load from default)'}")
            print(f"[PhaseLimiter] Mode: {self._mode} | "
                  f"level={self._params['level']:.2f} | "
                  f"loudness={self._params['loudness']:.1f}dB | "
                  f"bass={self._params['bass']} | "
                  f"mastering_mode={self._params['mode']}")
        else:
            print("[PhaseLimiter] [WARNING] Binary not found!")
            print("[PhaseLimiter] Run model downloader to install: python3 model_downloader.py --download")
            print("[PhaseLimiter] Or build from source: ./modules/external/phase/build_macos_native.sh")
            print("[PhaseLimiter] Falling back to Harman/Pedalboard chain.")

    def process(self, input_path: str, output_path: str, ffmpeg: str = "ffmpeg") -> bool:
        """
        Run phase_limiter on input_path → output_path.

        Args:
            input_path:  Path to input WAV (48 kHz, 24-bit recommended).
            output_path: Path to write mastered WAV.
            ffmpeg:      Path to ffmpeg binary (default 'ffmpeg' from PATH).

        Returns:
            True on success, False on failure.
        """
        if not self.available:
            return False

        p = self._params
        args = [
            self._binary,
            "--input",  input_path,
            "--output", output_path,
            "--ffmpeg", ffmpeg,
            "--mastering",              "true",
            "--mastering_mode",         p["mode"],
            "--mastering_matching_level",    _fmt_float(p["level"]),
            "--mastering_ms_matching_level", _fmt_float(p["level"]),
            "--mastering5_mastering_level",  _fmt_float(p["level"]),
            "--erb_eval_func_weighting",     _fmt_bool(p["bass"]),
            "--reference",              _fmt_float(p["loudness"]),
            "--reference_mode",         "loudness",
            "--ceiling",                _fmt_float(-0.5),
            "--ceiling_mode",           "true_peak",
            "--limiting_mode",          "phase",
            "--bit_depth",              "24",
            "--sample_rate",            "48000",
            "--worker_count",           "0",
        ]

        if self._cache:
            args += ["--sound_quality2_cache", self._cache]

        print(f"[PhaseLimiter] Running: {os.path.basename(self._binary)} "
              f"on {os.path.basename(input_path)}")

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            prog_re = re.compile(r"progression:\s*([\d.]+)")
            last_pct = -1
            for line in proc.stdout:
                line = line.rstrip()
                m = prog_re.search(line)
                if m:
                    pct = int(float(m.group(1)) * 100)
                    if pct != last_pct and pct % 10 == 0:
                        print(f"[PhaseLimiter] Progress: {pct}%")
                        last_pct = pct
                elif line:
                    print(f"[PhaseLimiter] {line}")

            proc.wait()
            if proc.returncode != 0:
                print(f"[PhaseLimiter] Binary exited with code {proc.returncode}")
                return False

            if not os.path.isfile(output_path):
                print(f"[PhaseLimiter] Output file not created: {output_path}")
                return False

            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"[PhaseLimiter] Done → {os.path.basename(output_path)} ({size_mb:.1f} MB)")
            return True

        except FileNotFoundError:
            print(f"[PhaseLimiter] Binary not executable: {self._binary}")
            return False
        except Exception as e:
            print(f"[PhaseLimiter] Error: {e}")
            return False
