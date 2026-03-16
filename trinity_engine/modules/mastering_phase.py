# VOXIS V4.0.0 DENSE — STAGE 6: MASTERING (Harman Target Curve)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Pedalboard-based mastering chain:
#   - Mid/Side stereo width control
#   - Harman target curve EQ (bass shelf + presence + treble rolloff)
#   - Spectral-adaptive Auto-EQ (HPF/LPF/vocal presence from analyzer)
#   - Peak normalization + Gain staging + Brickwall limiter
#   - Output validation

import os
import numpy as np
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir

# Pedalboard is the core DSP library
try:
    from pedalboard import (
        Pedalboard, Limiter, Gain,
        HighpassFilter, LowpassFilter, PeakFilter,
        LowShelfFilter, HighShelfFilter,
    )
    from pedalboard.io import AudioFile
    PEDALBOARD_AVAILABLE = True
except ImportError:
    PEDALBOARD_AVAILABLE = False


class PedalboardMastering:
    """
    Stage 6: Final mastering using Pedalboard DSP chain.
    Applies Harman target curve EQ, stereo width, gain staging, and limiting.

    Harman Target Curve Reference:
        Sean Olive et al., Harman International (2013-2018)
        - Bass shelf: +4 dB @ 105 Hz (Q=0.7)
        - Presence:   +1.5 dB @ 3 kHz (Q=1.0)
        - Treble:     -2.5 dB shelf @ 10 kHz (Q=0.7)
    """

    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        print(f"[{self.__class__.__name__}] Pedalboard: {'available' if PEDALBOARD_AVAILABLE else 'NOT FOUND'}")

        if not PEDALBOARD_AVAILABLE:
            print(f"[{self.__class__.__name__}] Install with: pip install pedalboard")

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
            lowpass_hz: Auto-EQ low pass cutoff from spectrum analyzer.
            highpass_hz: Auto-EQ high pass cutoff from spectrum analyzer.
            vocal_presence_db: Auto-EQ vocal presence boost/cut in dB.

        Returns:
            Path to mastered WAV.
        """
        fname = os.path.basename(input_audio_path)
        print(f"[{self.__class__.__name__}] Mastering: {fname}")
        print(f"[{self.__class__.__name__}] Width: {width * 100:.0f}% | "
              f"Gain: {gain_db:+.1f}dB | Ceiling: {limiter_threshold_db:.1f}dB")

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
                print(f"[{self.__class__.__name__}] Stereo width: {width * 100:.0f}%")

            # ── Step 2: Harman Target Curve EQ ───────────────────────
            harman_chain = self._build_harman_curve(highpass_hz, lowpass_hz, vocal_presence_db)
            board_eq = Pedalboard(harman_chain)
            audio = board_eq(audio, samplerate)
            print(f"[{self.__class__.__name__}] Harman curve EQ applied")

            # ── Step 3: Peak normalization → Gain → Limiter ──────────
            pre_peak = np.max(np.abs(audio))
            if pre_peak > 1e-6:
                target_peak = 10 ** (-1.0 / 20.0)  # -1 dBFS
                audio = audio * (target_peak / pre_peak)
                norm_db = 20 * np.log10(target_peak / pre_peak)
                print(f"[{self.__class__.__name__}] Peak normalized ({norm_db:+.1f}dB → -1 dBFS)")

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
                print(f"[{self.__class__.__name__}] Clip protection engaged (peak: {peak:.3f})")

            # ── Step 5: Write output ─────────────────────────────────
            with AudioFile(out_path, 'w', samplerate, audio.shape[0]) as f:
                f.write(audio)

            out_size = os.path.getsize(out_path)
            out_peak = np.max(np.abs(audio))
            out_rms = np.sqrt(np.mean(audio ** 2))
            out_db = 20 * np.log10(out_rms) if out_rms > 0 else -100.0

            print(f"[{self.__class__.__name__}] Mastered: {os.path.basename(out_path)} "
                  f"({out_size / 1024 / 1024:.1f} MB)")
            print(f"[{self.__class__.__name__}] Peak: {out_peak:.3f} | RMS: {out_db:.1f} dBFS")
            return out_path

        except Exception as e:
            print(f"[{self.__class__.__name__}] Mastering error: {e}")
            return input_audio_path

    def _build_harman_curve(self, highpass_hz: float, lowpass_hz: float,
                            vocal_presence_db: float) -> list:
        """
        Build the Harman target curve EQ chain, blended with
        spectral-adaptive Auto-EQ from the noise profiler.

        Harman curve (Sean Olive et al., 2013-2018):
          - Bass shelf:  +4 dB @ 105 Hz, Q=0.7
          - Mud cleanup: -1.5 dB @ 250 Hz, Q=0.8
          - Presence:    +1.5 dB @ 3 kHz, Q=1.0
          - De-harsh:    -1 dB @ 6.5 kHz, Q=1.5
          - Treble shelf: -2.5 dB @ 10 kHz, Q=0.7
          - Air rolloff:  LPF @ 18 kHz
        """
        effects = []

        # ── Subsonic HPF (max of Harman 25Hz and Auto-EQ HPF) ────
        hpf = max(25.0, float(highpass_hz))
        effects.append(HighpassFilter(cutoff_frequency_hz=hpf))

        # ── Harman bass shelf: +4 dB @ 105 Hz ───────────────────
        effects.append(LowShelfFilter(
            cutoff_frequency_hz=105.0,
            gain_db=4.0,
            q=0.7,
        ))

        # ── Low-mid cleanup: -1.5 dB @ 250 Hz ──────────────────
        effects.append(PeakFilter(
            cutoff_frequency_hz=250.0,
            gain_db=-1.5,
            q=0.8,
        ))

        # ── Presence / clarity: +1.5 dB @ 3 kHz ────────────────
        # Blend with Auto-EQ vocal presence
        presence = 1.5 + float(vocal_presence_db) * 0.5
        effects.append(PeakFilter(
            cutoff_frequency_hz=3000.0,
            gain_db=presence,
            q=1.0,
        ))

        # ── Harshness taming: -1 dB @ 6.5 kHz ──────────────────
        effects.append(PeakFilter(
            cutoff_frequency_hz=6500.0,
            gain_db=-1.0,
            q=1.5,
        ))

        # ── Harman treble rolloff: -2.5 dB shelf @ 10 kHz ──────
        effects.append(HighShelfFilter(
            cutoff_frequency_hz=10000.0,
            gain_db=-2.5,
            q=0.7,
        ))

        # ── Air rolloff LPF (min of 18kHz and Auto-EQ LPF) ─────
        lpf = min(18000.0, float(lowpass_hz))
        effects.append(LowpassFilter(cutoff_frequency_hz=lpf))

        print(f"[{self.__class__.__name__}] Harman EQ: "
              f"HPF={hpf:.0f}Hz | Bass=+4dB@105Hz | "
              f"Presence={presence:+.1f}dB@3kHz | "
              f"Treble=-2.5dB@10kHz | LPF={lpf:.0f}Hz")

        return effects

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

        side = side * width

        new_left = mid + side
        new_right = mid - side

        return np.array([new_left, new_right])
