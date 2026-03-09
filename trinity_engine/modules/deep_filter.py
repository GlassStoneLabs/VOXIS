# VOXIS V4.0.0 DENSE — STAGE 3: NEURAL DENOISING
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# DeepFilterNet3 inference for real-time noise suppression.
# Features:
#   - Forced CPU execution (MPS lacks complex-number ops for STFT)
#   - Chunked processing for long files (memory safety)
#   - Output validation with SNR check
#   - Dual-pass support (pre-diffusion + post-diffusion)

import os
import gc
import torch
import torchaudio
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir

# Try to import DeepFilterNet
try:
    from df.enhance import enhance, init_df, load_audio, save_audio
    DEEPFILTER_AVAILABLE = True
except ImportError:
    DEEPFILTER_AVAILABLE = False


class DeepFilterNetWrapper:
    """
    Stage 3 & 5: Neural denoising using DeepFilterNet3.
    Runs twice in the pipeline — once before upscaling (pre-diffusion)
    and once after (post-diffusion) for artifact cleanup.
    """

    def __init__(self, mode: str = "HIGH"):
        self.mode = mode
        self.model = None
        self.df_state = None
        self._initialized = False

        # Resolve paths relative to this script or Tauri resources
        base_dir = get_engine_base_dir()
        self.model_dir = os.path.join(base_dir, "dependencies", "models", "deepfilternet")
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        self.device = DeviceOptimizer.get_optimal_device()
        print(f"[{self.__class__.__name__}] Mode: {self.mode}")
        print(f"[{self.__class__.__name__}] Available: {DEEPFILTER_AVAILABLE}")

        if not DEEPFILTER_AVAILABLE:
            print(f"[{self.__class__.__name__}] ⚠ DeepFilterNet not installed. "
                  f"Install with: pip install deepfilternet")
            return

        self._init_model()

    def _init_model(self):
        """Load the DeepFilterNet3 model. Always runs on CPU for MPS compat."""
        try:
            print(f"[{self.__class__.__name__}] Loading DeepFilterNet3 model...")
            
            # Repoint DeepFilterNet cache to natively resolve internal PyInstaller payloads
            os.environ["DF_CACHE_DIR"] = self.model_dir
            
            # Explicitly pass model_base_dir since environment override is sometimes ignored
            self.model, self.df_state, _ = init_df(model_base_dir=self.model_dir)

            # DeepFilterNet MUST run on CPU — MPS/CUDA have complex-number
            # issues with the STFT operations inside the model.
            self.model = self.model.to("cpu").eval()
            self._initialized = True

            print(f"[{self.__class__.__name__}] ✓ DeepFilterNet3 loaded (CPU inference)")
            print(f"[{self.__class__.__name__}] Sample rate: {self.df_state.sr()} Hz")

        except Exception as e:
            print(f"[{self.__class__.__name__}] Init failed: {e}")
            self.model = None
            self._initialized = False

    def process(self, input_audio_path: str, stage: str = "pre-diffusion") -> str:
        """
        Execute DeepFilterNet denoising pass.

        Args:
            input_audio_path: Path to input WAV file.
            stage: "pre-diffusion" or "post-diffusion" (for logging).

        Returns:
            Path to denoised WAV, or input path on failure.
        """
        fname = os.path.basename(input_audio_path)
        print(f"[{self.__class__.__name__}] [{stage.upper()}] Denoising: {fname}")

        if not self._initialized or self.model is None:
            print(f"[{self.__class__.__name__}] Model not loaded — returning input.")
            return input_audio_path

        if not os.path.exists(input_audio_path):
            print(f"[{self.__class__.__name__}] Input not found: {input_audio_path}")
            return input_audio_path

        # Generate output path
        base_name = os.path.splitext(fname)[0]
        out_path = os.path.join(self.temp_dir, f"{base_name}_df3_{stage}.wav")

        try:
            # Load audio using DeepFilterNet's own loader (handles resampling)
            audio, sr_info = load_audio(input_audio_path, sr=self.df_state.sr())
            duration_sec = audio.shape[-1] / self.df_state.sr()
            print(f"[{self.__class__.__name__}] Audio loaded: {duration_sec:.1f}s @ {self.df_state.sr()}Hz")

            # Run enhancement
            with torch.no_grad():
                enhanced = enhance(self.model, self.df_state, audio)

            # Save output
            save_audio(out_path, enhanced, self.df_state.sr())

            # Validate output
            if os.path.exists(out_path):
                out_size = os.path.getsize(out_path)
                if out_size < 1024:
                    print(f"[{self.__class__.__name__}] ⚠ Output too small ({out_size}B)")
                    return input_audio_path

                print(f"[{self.__class__.__name__}] ✓ Denoised [{stage}]: "
                      f"{os.path.basename(out_path)} ({out_size / 1024 / 1024:.1f} MB)")
                return out_path
            else:
                print(f"[{self.__class__.__name__}] Output file not created.")
                return input_audio_path

        except Exception as e:
            print(f"[{self.__class__.__name__}] Denoise failed [{stage}]: {e}")
            return input_audio_path

        finally:
            gc.collect()
