# VOXIS V4.0.0 DENSE — STAGE 4: AUDIO SUPER-RESOLUTION
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# AudioSR latent diffusion upsampling to 48kHz.
# Features:
#   - Cross-platform device support (CUDA/MPS/CPU)
#   - Configurable DDIM steps (quality vs speed tradeoff)
#   - Output validation with sample rate verification
#   - Memory cleanup after diffusion
#   - Graceful fallback: if AudioSR unavailable, use torchaudio resampling

import os
# Must be set before any torch import
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
import gc
import torch
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir

# Try to import AudioSR safely
try:
    from audiosr import super_resolution, build_model
    AUDIOSR_AVAILABLE = True
except ImportError:
    AUDIOSR_AVAILABLE = False

# Torchaudio is always available as a fallback for basic resampling
import torchaudio


class TrinityUpscaler:
    """
    Stage 4: Audio Super-Resolution using AudioSR latent diffusion.
    Upsamples audio from 44.1kHz to 48kHz with bandwidth extension.
    Falls back to torchaudio.transforms.Resample if AudioSR unavailable.
    """

    # Quality presets (DDIM steps)
    PRESETS = {
        "FAST":     20,   # ~30s per track
        "HIGH":     50,   # ~75s per track (default)
        "EXTREME": 100,   # ~150s per track
    }

    def __init__(self, device=None, quality: str = "HIGH"):
        self.device = device or DeviceOptimizer.get_optimal_device()
        self.device_str = DeviceOptimizer.get_device_string()
        self.ddim_steps = self.PRESETS.get(quality, 50)
        self.audiosr_model = None
        self._initialized = False

        # Resolve paths
        base_dir = get_engine_base_dir()
        self.cache_dir = os.path.join(base_dir, "dependencies", "models", "huggingface")
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        print(f"[{self.__class__.__name__}] Device: {self.device_str.upper()}")
        print(f"[{self.__class__.__name__}] AudioSR: {'available' if AUDIOSR_AVAILABLE else 'NOT FOUND (using resample fallback)'}")
        print(f"[{self.__class__.__name__}] Quality: {quality} ({self.ddim_steps} DDIM steps)")

        if AUDIOSR_AVAILABLE:
            self._init_audiosr()

    def _init_audiosr(self):
        """Initialize AudioSR latent diffusion model."""
        try:
            # Set HuggingFace cache directory
            os.environ["HUGGINGFACE_HUB_CACHE"] = self.cache_dir
            os.environ["AUDIOSR_CACHE_DIR"] = self.cache_dir

            print(f"[{self.__class__.__name__}] Loading AudioSR model (will download on first run)...")
            self.audiosr_model = build_model(model_name="basic", device=self.device_str)
            self._initialized = True
            print(f"[{self.__class__.__name__}] ✓ AudioSR model loaded on {self.device_str}")

        except Exception as e:
            print(f"[{self.__class__.__name__}] AudioSR init failed: {e}")
            print(f"[{self.__class__.__name__}] Will use torchaudio resample fallback.")
            self._initialized = False

    def super_resolve(self, input_audio_path: str, target_sr: int = 48000) -> str:
        """
        Upscale audio to target sample rate.
        Uses AudioSR diffusion if available, otherwise torchaudio resample.

        Args:
            input_audio_path: Path to input WAV.
            target_sr: Target sample rate (default 48000 Hz).

        Returns:
            Path to upsampled WAV file.
        """
        fname = os.path.basename(input_audio_path)
        print(f"[{self.__class__.__name__}] Upscaling: {fname} → {target_sr}Hz")

        if not os.path.exists(input_audio_path):
            print(f"[{self.__class__.__name__}] Input not found.")
            return input_audio_path

        out_path = os.path.join(self.temp_dir, f"upscaled_{fname}")

        # Try AudioSR first
        if self._initialized and self.audiosr_model:
            result = self._audiosr_upscale(input_audio_path, out_path, target_sr)
            if result:
                return result

        # Fallback: torchaudio resample
        return self._resample_fallback(input_audio_path, out_path, target_sr)

    def _audiosr_upscale(self, input_path: str, out_path: str, target_sr: int) -> str | None:
        """Run AudioSR latent diffusion upsampling."""
        try:
            # Pre-check: AudioSR's internal resampler can crash if the
            # Butterworth filter Wn parameter falls outside (0, 1).
            # This happens when the source SR is very close to or exceeds
            # the AudioSR internal target. Fall back immediately if so.
            import soundfile as sf
            info = sf.info(input_path)
            if info.samplerate >= target_sr:
                print(f"[{self.__class__.__name__}] Source SR ({info.samplerate}Hz) >= target ({target_sr}Hz), "
                      f"skipping AudioSR diffusion (Wn guard).")
                return None

            print(f"[{self.__class__.__name__}] Running AudioSR diffusion ({self.ddim_steps} DDIM steps)...")

            with torch.no_grad():
                waveform = super_resolution(
                    self.audiosr_model,
                    input_path,
                    seed=42,
                    guidance_scale=3.5,
                    ddim_steps=self.ddim_steps,
                )

            if waveform is not None:
                # AudioSR may return numpy array or torch tensor
                import numpy as np
                if isinstance(waveform, np.ndarray):
                    waveform = torch.from_numpy(waveform)

                # Force to CPU immediately for saving
                if hasattr(waveform, 'cpu'):
                    waveform = waveform.cpu()

                # AudioSR may return (batch, channels, samples) or (batch, 1, channels, samples).
                # Squeeze all size-1 dims first, then force to 2D if still higher.
                waveform = waveform.squeeze()   # collapse all unit dims
                if waveform.dim() > 2:
                    # e.g. (2, channels, samples) — flatten leading dims into channels
                    waveform = waveform.reshape(-1, waveform.shape[-1])

                # Ensure 2D: (channels, samples)
                if waveform.dim() == 1:
                    waveform = waveform.unsqueeze(0)

                # Limit to stereo max
                if waveform.shape[0] > 2:
                    waveform = waveform[:2, :]

                # Normalize if needed
                peak = torch.max(torch.abs(waveform))
                if peak > 1.0:
                    waveform = waveform / peak

                # Convert to float32 for torchaudio
                waveform = waveform.to(torch.float32)

                torchaudio.save(out_path, waveform, target_sr)

                out_size = os.path.getsize(out_path)
                print(f"[{self.__class__.__name__}] ✓ AudioSR upscale complete: "
                      f"{os.path.basename(out_path)} ({out_size / 1024 / 1024:.1f} MB)")
                return out_path

            print(f"[{self.__class__.__name__}] AudioSR returned None, falling back.")
            return None

        except Exception as e:
            err_str = str(e)
            if "Wn" in err_str or "critical frequencies" in err_str:
                print(f"[{self.__class__.__name__}] AudioSR Butterworth filter error (Wn out of range) — "
                      f"falling back to torchaudio resample.")
            else:
                print(f"[{self.__class__.__name__}] AudioSR failed: {e}")
            return None

        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
                torch.mps.empty_cache()

    def _resample_fallback(self, input_path: str, out_path: str, target_sr: int) -> str:
        """
        Fallback: use torchaudio.transforms.Resample for basic upsampling.
        No bandwidth extension, but reliable and fast.
        """
        try:
            print(f"[{self.__class__.__name__}] Using torchaudio resample fallback...")
            audio, sr = torchaudio.load(input_path)

            if sr == target_sr:
                print(f"[{self.__class__.__name__}] Already at {target_sr}Hz, skipping.")
                return input_path

            resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)
            resampled = resampler(audio)

            torchaudio.save(out_path, resampled, target_sr)

            out_size = os.path.getsize(out_path)
            print(f"[{self.__class__.__name__}] ✓ Resampled {sr}→{target_sr}Hz: "
                  f"{os.path.basename(out_path)} ({out_size / 1024 / 1024:.1f} MB)")
            return out_path

        except Exception as e:
            print(f"[{self.__class__.__name__}] Resample fallback failed: {e}")
            return input_path
