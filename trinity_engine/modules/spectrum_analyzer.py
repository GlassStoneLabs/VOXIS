# VOXIS V4.0.0 DENSE — Spectrum Analyzer
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.

import os
import math
import torch
import torchaudio
from .device_utils import DeviceOptimizer


class NoiseProfiler:
    """
    Spectral analysis & noise profiling module for the Trinity V8.2 pipeline.
    Calculates RMS, noise floor dB, spectral centroid, spectral rolloff,
    and dynamic range. Used to auto-compute EQ and denoise aggressiveness.
    """

    def __init__(self, device=None):
        self.device = device if device else DeviceOptimizer.get_optimal_device()
        print(f"[{self.__class__.__name__}] Initializing Analyzer on {self.device}...")

    def analyze(self, audio_file_path: str) -> dict:
        """
        Profile noise characteristics from the provided WAV file.
        Returns a dictionary with noise floor metrics and auto-EQ recommendations.
        """
        print(f"[{self.__class__.__name__}] Profiling noise floor: {os.path.basename(audio_file_path)}")

        try:
            # Load only up to 30s for spectral analysis — no quality loss,
            # profile is statistical and converges well within this window
            info = torchaudio.info(audio_file_path)
            sr = info.sample_rate
            total_frames = info.num_frames
            max_analysis_frames = min(total_frames, sr * 30)
            audio_tensor, sr = torchaudio.load(
                audio_file_path, num_frames=max_analysis_frames
            )

            # Move to CPU for reliable math (MPS has complex-number issues)
            if audio_tensor.device.type != 'cpu':
                audio_tensor = audio_tensor.to("cpu")

            # ── RMS & dBFS ───────────────────────────────────────────
            rms = torch.sqrt(torch.mean(audio_tensor ** 2)).item()
            dbfs = 20 * math.log10(rms) if rms > 0 else -100.0

            # ── Peak amplitude ───────────────────────────────────────
            peak = audio_tensor.abs().max().item()
            peak_db = 20 * math.log10(peak) if peak > 0 else -100.0

            # ── Dynamic range (peak - rms in dB) ─────────────────────
            dynamic_range_db = peak_db - dbfs

            # ── Spectral analysis ────────────────────────────────────
            n_fft = min(2048, audio_tensor.shape[-1])
            spectral_centroid_hz = 0.0
            spectral_rolloff_hz = 20000.0
            useful_low_hz = 20.0
            vocal_energy_ratio = 0.0

            if audio_tensor.shape[-1] >= n_fft:
                # Mono mix for spectral analysis
                mono = audio_tensor.mean(dim=0)
                del audio_tensor  # Free multi-channel tensor early
                window = torch.hann_window(n_fft)
                stft = torch.stft(mono, n_fft=n_fft, return_complex=True, window=window)
                del mono
                magnitudes = stft.abs()
                del stft

                # Mean magnitude per frequency bin (average over time frames)
                # Compute mean_mag first, then derive centroid from 1D vector — avoids
                # the large (n_freqs, n_frames) intermediate from freqs * magnitudes
                mean_mag = magnitudes.mean(dim=1)
                del magnitudes
                freqs = torch.linspace(0, sr / 2, mean_mag.shape[0])
                total_energy = mean_mag.sum().item() + 1e-8

                # Spectral centroid from mean magnitudes (1D dot product, not 2D broadcast)
                spectral_centroid_hz = (freqs * mean_mag).sum().item() / total_energy

                # Spectral rolloff — frequency below which 95% of energy resides
                cumulative = torch.cumsum(mean_mag, dim=0)
                rolloff_idx = torch.searchsorted(cumulative, 0.95 * cumulative[-1]).item()
                rolloff_idx = min(rolloff_idx, len(freqs) - 1)
                spectral_rolloff_hz = freqs[rolloff_idx].item()

                # Useful low-end — frequency above which 2% of energy starts
                low_idx = torch.searchsorted(cumulative, 0.02 * cumulative[-1]).item()
                low_idx = min(low_idx, len(freqs) - 1)
                useful_low_hz = max(20.0, freqs[low_idx].item())

                # Vocal energy ratio — energy in 1kHz–5kHz vs total
                vocal_mask = (freqs >= 1000) & (freqs <= 5000)
                vocal_energy = mean_mag[vocal_mask].sum().item()
                vocal_energy_ratio = vocal_energy / total_energy
            else:
                del audio_tensor

            # ── Duration (use full file, not analysis window) ─────────
            duration_sec = total_frames / sr

            profile = {
                "rms": round(rms, 6),
                "dbfs": round(dbfs, 2),
                "peak_db": round(peak_db, 2),
                "dynamic_range_db": round(dynamic_range_db, 2),
                "spectral_centroid_hz": round(spectral_centroid_hz, 1),
                "spectral_rolloff_hz": round(spectral_rolloff_hz, 1),
                "useful_low_hz": round(useful_low_hz, 1),
                "vocal_energy_ratio": round(vocal_energy_ratio, 4),
                "sample_rate": sr,
                "channels": info.num_channels,
                "duration_sec": round(duration_sec, 2),
            }

            print(f"[{self.__class__.__name__}] Noise Floor: {dbfs:.1f} dBFS | "
                  f"Peak: {peak_db:.1f} dBFS | DR: {dynamic_range_db:.1f} dB | "
                  f"Centroid: {spectral_centroid_hz:.0f} Hz")
            print(f"[{self.__class__.__name__}] Rolloff: {spectral_rolloff_hz:.0f}Hz | "
                  f"Useful Low: {useful_low_hz:.0f}Hz | "
                  f"Vocal Ratio: {vocal_energy_ratio:.2%}")

            return profile

        except Exception as e:
            print(f"[{self.__class__.__name__}] Profile Error: {e}")
            return {"rms": 0.0, "dbfs": -100.0, "peak_db": -100.0,
                    "dynamic_range_db": 0.0, "spectral_centroid_hz": 0.0,
                    "spectral_rolloff_hz": 20000.0, "useful_low_hz": 20.0,
                    "vocal_energy_ratio": 0.0,
                    "sample_rate": 0, "channels": 0, "duration_sec": 0.0}

    @staticmethod
    def compute_auto_eq(profile: dict) -> dict:
        """
        Derive optimal EQ settings from the spectral profile.
        Returns a dict with lowpass_hz, highpass_hz, and vocal_presence_db.
        """
        # Auto low pass: set to rolloff + 10% headroom, clamped to 14kHz–20kHz
        # (Floor of 14kHz preserves brightness and harmonics)
        rolloff = profile.get("spectral_rolloff_hz", 20000.0)
        auto_lpf = min(20000.0, max(14000.0, rolloff * 1.1))

        # Auto high pass: set to useful low frequency, clamped to 20–80Hz
        # (Cap at 80Hz protects vocal fundamentals and bass content)
        useful_low = profile.get("useful_low_hz", 20.0)
        auto_hpf = min(80.0, max(20.0, useful_low))

        # Auto vocal presence: boost if vocal energy is low, cut if harsh
        vocal_ratio = profile.get("vocal_energy_ratio", 0.0)
        centroid = profile.get("spectral_centroid_hz", 0.0)

        if vocal_ratio < 0.15:
            # Low vocal energy — boost presence
            vocal_db = min(4.0, (0.15 - vocal_ratio) * 30.0)
        elif vocal_ratio > 0.40:
            # Harsh/sibilant — cut presence
            vocal_db = max(-1.5, -(vocal_ratio - 0.40) * 15.0)
        else:
            vocal_db = 0.0

        # If centroid is very high (bright/harsh), apply gentle LPF taming
        if centroid > 4000:
            auto_lpf = min(auto_lpf, 18000.0)

        eq = {
            "lowpass_hz": round(auto_lpf, 0),
            "highpass_hz": round(auto_hpf, 0),
            "vocal_presence_db": round(vocal_db, 1),
        }

        print(f"[NoiseProfiler] Auto-EQ: HPF={eq['highpass_hz']:.0f}Hz | "
              f"LPF={eq['lowpass_hz']:.0f}Hz | "
              f"Vocal={eq['vocal_presence_db']:+.1f}dB")

        return eq

