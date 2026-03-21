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
import torch
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir
from .coreml_bridge import CoreMLBridge, CoreMLModule, coreml_viable

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

        # CoreML acceleration state
        self._coreml_bridge    = CoreMLBridge() if coreml_viable() else None
        self._coreml_denoiser  = None   # AudioSR UNet → CoreML
        self._coreml_active    = False

        # Resolve paths
        base_dir = get_engine_base_dir()
        self.cache_dir = os.path.join(base_dir, "dependencies", "models", "huggingface")
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        print(f"[{self.__class__.__name__}] Device: {self.device_str.upper()}")
        print(f"[{self.__class__.__name__}] GS-ASCEND: {'available' if AUDIOSR_AVAILABLE else 'NOT FOUND (using resample fallback)'}")
        print(f"[{self.__class__.__name__}] Quality: {quality} ({self.ddim_steps} DDIM steps)")

        if AUDIOSR_AVAILABLE:
            self._init_audiosr()

    def _init_audiosr(self):
        """Initialize AudioSR latent diffusion model."""
        try:
            # Set HuggingFace cache directory
            os.environ["HUGGINGFACE_HUB_CACHE"] = self.cache_dir
            os.environ["AUDIOSR_CACHE_DIR"] = self.cache_dir

            print(f"[{self.__class__.__name__}] Loading GS-ASCEND model (will download on first run)...")
            self.audiosr_model = build_model(model_name="basic", device=self.device_str)
            self._initialized = True
            print(f"[{self.__class__.__name__}] ✓ GS-ASCEND model loaded on {self.device_str}")

            # Attempt CoreML acceleration of the AudioSR denoiser (UNet)
            if coreml_viable():
                self._try_coreml_acceleration()

        except Exception as e:
            print(f"[{self.__class__.__name__}] AudioSR init failed: {e}")
            print(f"[{self.__class__.__name__}] Will use torchaudio resample fallback.")
            self._initialized = False

    def _try_coreml_acceleration(self):
        """
        Attempt to convert AudioSR's internal UNet denoiser to CoreML.

        AudioSR model hierarchy (duck-typed — structure varies by version):
          audiosr_model           → dict or object returned by build_model()
          audiosr_model['model']  → LatentDiffusion
          .model                  → UNet denoiser (the hot loop)

        On success: the UNet's __call__ is replaced with a CoreMLModule
        wrapper so each DDIM step runs on the Neural Engine.
        """
        bridge = self._coreml_bridge
        if bridge is None:
            return

        print(f"[{self.__class__.__name__}] Attempting GS-ASCEND CoreML denoiser conversion...")

        try:
            # Resolve the UNet — AudioSR can store model in a dict or as attrs
            ldm = None
            if isinstance(self.audiosr_model, dict):
                ldm = self.audiosr_model.get("model")
            elif hasattr(self.audiosr_model, "model"):
                ldm = self.audiosr_model.model

            unet = None
            if ldm is not None:
                # Try common attribute names for the denoising network
                for attr in ("model", "diffusion_model", "unet", "denoiser"):
                    candidate = getattr(ldm, attr, None)
                    if candidate is not None and isinstance(candidate, torch.nn.Module):
                        unet = candidate
                        break

            if unet is None:
                print(f"[{self.__class__.__name__}] Could not locate UNet — "
                      "GS-ASCEND CoreML skipped (PyTorch path active)")
                return

            # Probe the UNet's expected input shapes with a dummy forward pass
            # AudioSR UNet typically: x=(B,C,T), t=(B,), context=(B,S,D)
            # We use small safe defaults and let trace figure out the shapes
            unet.eval()
            # Try to infer channel count from first conv layer
            c_in = 8
            for module in unet.modules():
                if isinstance(module, torch.nn.Conv1d):
                    c_in = module.in_channels
                    break
                if isinstance(module, torch.nn.Conv2d):
                    c_in = module.in_channels
                    break

            dummy_x   = torch.zeros(1, c_in, 256).cpu()
            dummy_t   = torch.zeros(1).long().cpu()

            coreml_unet = bridge.convert(
                unet,
                sample_inputs=(dummy_x, dummy_t),
                model_name=f"gs_ascend_unet_cin{c_in}",
                input_names=["noisy_latent", "timestep"],
                output_names=["denoised_latent"],
                dynamic_axes={"noisy_latent": [2]},   # time dimension is dynamic
            )

            if coreml_unet:
                wrapped_unet = CoreMLModule(
                    original=unet,
                    coreml=coreml_unet,
                    input_name="noisy_latent",
                    output_name="denoised_latent",
                    bridge=bridge,
                )
                # Patch UNet back into AudioSR's model hierarchy
                if ldm is not None:
                    for attr in ("model", "diffusion_model", "unet", "denoiser"):
                        if hasattr(ldm, attr) and isinstance(getattr(ldm, attr), torch.nn.Module):
                            setattr(ldm, attr, wrapped_unet)
                            break
                self._coreml_denoiser = coreml_unet
                self._coreml_active   = True
                print(f"[{self.__class__.__name__}] ✓ GS-ASCEND denoiser on Neural Engine (CoreML)")
            else:
                print(f"[{self.__class__.__name__}] UNet CoreML conversion unavailable — "
                      "running standard DDIM sampling")

        except Exception as e:
            print(f"[{self.__class__.__name__}] GS-ASCEND CoreML skipped: {e}")

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

            print(f"[{self.__class__.__name__}] Running GS-ASCEND diffusion ({self.ddim_steps} DDIM steps)...")

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
            DeviceOptimizer.cleanup_memory()

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
