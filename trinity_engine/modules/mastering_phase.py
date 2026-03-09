# VOXIS V4.0.0 DENSE — STAGE 6: MASTERING
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Pedalboard-based mastering chain:
#   - Mid/Side stereo width control
#   - Multi-band EQ sweetening (optional)
#   - Gain staging + brickwall limiter at 0 dBFS
#   - Dither for final bit-depth conversion
#   - Output validation

import os
import numpy as np
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir

# Pedalboard is the core DSP library
try:
    from pedalboard import Pedalboard, Limiter, Gain, HighpassFilter, LowpassFilter
    from pedalboard.io import AudioFile
    PEDALBOARD_AVAILABLE = True
    # PeakFilter for vocal EQ (available in pedalboard >= 0.7)
    try:
        from pedalboard import PeakFilter
        PEAK_FILTER_AVAILABLE = True
    except ImportError:
        PEAK_FILTER_AVAILABLE = False
except ImportError:
    PEDALBOARD_AVAILABLE = False
    PEAK_FILTER_AVAILABLE = False


class PedalboardMastering:
    """
    Stage 6: Final mastering using Pedalboard DSP chain.
    Applies stereo width, EQ, gain staging, and limiting.
    """

    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        print(f"[{self.__class__.__name__}] Pedalboard: {'available' if PEDALBOARD_AVAILABLE else 'NOT FOUND'}")

        if not PEDALBOARD_AVAILABLE:
            print(f"[{self.__class__.__name__}] ⚠ Install with: pip install pedalboard")

    def apply(self, input_audio_path: str, width: float = 0.50,
              gain_db: float = 2.0, limiter_threshold_db: float = -0.3,
              lowpass_hz: float = 20000.0, highpass_hz: float = 20.0,
              vocal_presence_db: float = 0.0) -> str:
        """
        Apply the full mastering chain to the input audio.

        Args:
            input_audio_path: Path to input WAV.
            width: Stereo width multiplier (0.0=mono, 1.0=normal, >1.0=wider).
            gain_db: Pre-limiter gain boost in dB.
            limiter_threshold_db: Brickwall limiter ceiling.
            lowpass_hz: Low pass filter cutoff (1000–20000 Hz).
            highpass_hz: High pass filter cutoff (20–2000 Hz).
            vocal_presence_db: Vocal presence EQ boost/cut in dB (-6 to +6).

        Returns:
            Path to mastered WAV.
        """
        fname = os.path.basename(input_audio_path)
        print(f"[{self.__class__.__name__}] Mastering: {fname}")
        print(f"[{self.__class__.__name__}] Width: {width * 100:.0f}% | "
              f"Gain: {gain_db:+.1f}dB | Ceiling: {limiter_threshold_db:.1f}dB")
        print(f"[{self.__class__.__name__}] EQ: HPF={highpass_hz:.0f}Hz | "
              f"LPF={lowpass_hz:.0f}Hz | Vocal={vocal_presence_db:+.1f}dB")

        if not PEDALBOARD_AVAILABLE:
            print(f"[{self.__class__.__name__}] Pedalboard not available — returning input.")
            return input_audio_path

        if not os.path.exists(input_audio_path):
            print(f"[{self.__class__.__name__}] Input not found.")
            return input_audio_path

        out_path = os.path.join(self.temp_dir, f"mastered_{fname}")

        try:
            # Load audio
            with AudioFile(input_audio_path) as f:
                audio = f.read(f.frames)
                samplerate = f.samplerate
                channels = f.num_channels

            print(f"[{self.__class__.__name__}] Loaded: {channels}ch @ {samplerate}Hz "
                  f"({audio.shape[-1] / samplerate:.1f}s)")

            # ── Step 1: Stereo Width (Mid/Side processing) ───────────
            if channels == 2 and abs(width - 1.0) > 0.01:
                audio = self._apply_stereo_width(audio, width)
                print(f"[{self.__class__.__name__}] ✓ Stereo width applied ({width * 100:.0f}%)")

            # ── Step 2: User EQ chain (HPF + LPF + Vocal Presence) ─────
            eq_effects = []
            # High pass filter (remove low-end rumble / mud)
            if highpass_hz > 20:
                eq_effects.append(HighpassFilter(cutoff_frequency_hz=float(highpass_hz)))
                print(f"[{self.__class__.__name__}] ✓ High pass filter: {highpass_hz:.0f}Hz")
            else:
                # Default subsonic filter only
                eq_effects.append(HighpassFilter(cutoff_frequency_hz=30.0))

            # Low pass filter (tame harsh highs)
            if lowpass_hz < 20000:
                eq_effects.append(LowpassFilter(cutoff_frequency_hz=float(lowpass_hz)))
                print(f"[{self.__class__.__name__}] ✓ Low pass filter: {lowpass_hz:.0f}Hz")

            # Vocal presence EQ (2.5kHz peak bell filter)
            if abs(vocal_presence_db) > 0.1 and PEAK_FILTER_AVAILABLE:
                eq_effects.append(PeakFilter(
                    cutoff_frequency_hz=2500.0,
                    gain_db=float(vocal_presence_db),
                    q=1.2,
                ))
                print(f"[{self.__class__.__name__}] ✓ Vocal presence: {vocal_presence_db:+.1f}dB @ 2.5kHz")

            if eq_effects:
                board_eq = Pedalboard(eq_effects)
                audio = board_eq(audio, samplerate)

            # ── Step 3: Gain staging + Brickwall limiter ─────────────
            board_main = Pedalboard([
                Gain(gain_db=gain_db),
                Limiter(
                    threshold_db=limiter_threshold_db,
                    release_ms=100.0,
                ),
            ])
            audio = board_main(audio, samplerate)

            # ── Step 4: Clip protection ──────────────────────────────
            peak = np.max(np.abs(audio))
            if peak > 1.0:
                audio = audio / peak
                print(f"[{self.__class__.__name__}] ⚠ Clip protection engaged (peak: {peak:.3f})")

            # ── Step 5: Write output ─────────────────────────────────
            with AudioFile(out_path, 'w', samplerate, audio.shape[0]) as f:
                f.write(audio)

            out_size = os.path.getsize(out_path)
            out_peak = np.max(np.abs(audio))
            out_rms = np.sqrt(np.mean(audio ** 2))
            out_db = 20 * np.log10(out_rms) if out_rms > 0 else -100.0

            print(f"[{self.__class__.__name__}] ✓ Mastered: {os.path.basename(out_path)} "
                  f"({out_size / 1024 / 1024:.1f} MB)")
            print(f"[{self.__class__.__name__}] Peak: {out_peak:.3f} | RMS: {out_db:.1f} dBFS")
            return out_path

        except Exception as e:
            print(f"[{self.__class__.__name__}] Mastering error: {e}")
            return input_audio_path

    def _apply_stereo_width(self, audio: np.ndarray, width: float) -> np.ndarray:
        """
        Apply stereo width using Mid/Side processing.
        width < 1.0 = narrower (toward mono)
        width = 1.0 = unchanged
        width > 1.0 = wider (exaggerated stereo)
        """
        left = audio[0, :]
        right = audio[1, :]

        mid = (left + right) / 2.0
        side = (left - right) / 2.0

        # Scale the side channel
        side = side * width

        new_left = mid + side
        new_right = mid - side

        return np.array([new_left, new_right])
