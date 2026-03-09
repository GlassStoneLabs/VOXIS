# VOXIS V4.0.0 DENSE — STAGE 3: UNIVERSAL RESTORATION
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# VoiceRestore: Transformer-Diffusion Model for Universal Restoration
#
# MPS NOTE: BigVGAN uses depthwise/pointwise conv layers with output channels > 65536.
# PyTorch MPS firmware does NOT support this even with PYTORCH_ENABLE_MPS_FALLBACK=1.
# The only reliable fix is to run the full VoiceRestore inference on CPU when MPS
# is detected. This sacrifices MPS speed but guarantees correctness.

import os
import sys

# Must be set before any torch import to enable CPU fallback for unsupported MPS ops.
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import torch
import torchaudio
import gc
from huggingface_hub import hf_hub_download
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir

# Path resolution for VoiceRestore and BigVGAN
current_dir = os.path.dirname(os.path.abspath(__file__))
voicerestore_dir = os.path.join(current_dir, "external", "voicerestore")
bigvgan_dir = os.path.join(voicerestore_dir, "BigVGAN")

if bigvgan_dir not in sys.path:
    sys.path.append(bigvgan_dir)
if voicerestore_dir not in sys.path:
    sys.path.append(voicerestore_dir)

try:
    from model import OptimizedAudioRestorationModel
    import bigvgan
except ImportError as e:
    print(f"[VoiceRestoreWrapper] ImportError: {e}")

class VoiceRestoreWrapper:
    """
    Stage 3 & 5: Universal Restoration using VoiceRestore (Transformer-Diffusion).
    Replaces older DeepFilterNet with a unified 301M parameter flow-matching model.

    On Apple Silicon (MPS): runs inference on CPU because BigVGAN uses conv layers
    with output_channels > 65536 which is a hard MPS firmware limit.
    """

    def __init__(self, mode: str = "HIGH"):
        self.mode = mode
        self.raw_device = DeviceOptimizer.get_optimal_device()

        # BigVGAN exceeds MPS channel limits — force CPU for inference device
        if self.raw_device == "mps":
            self.device = "cpu"
            print("[VoiceRestoreWrapper] MPS detected — forcing inference to CPU "
                  "(BigVGAN channels > 65536 exceed MPS firmware limits)")
        else:
            self.device = self.raw_device

        self.model = None
        self.bigvgan_model = None
        self._initialized = False

        # Configure intensity parameters based on mode
        self.steps = 32 if mode == "EXTREME" else 16
        self.cfg_strength = 1.0 if mode == "EXTREME" else 0.5

    def _initialize_model(self):
        if self._initialized:
            return
        print(f"[{self.__class__.__name__}] Initializing VoiceRestore on {self.device}...")

        try:
            # 1. Init BigVGAN vocoder on the forced inference device (CPU for MPS hosts)
            
            # Map PyInstaller local payloads for BigVGAN's huggingface downloader logic
            target_hf_cache = os.path.join(get_engine_base_dir(), "dependencies", "models", "huggingface")
            os.environ["HUGGINGFACE_HUB_CACHE"] = target_hf_cache
            
            self.bigvgan_model = bigvgan.BigVGAN.from_pretrained(
                'nvidia/bigvgan_v2_24khz_100band_256x',
                use_cuda_kernel=False,
                cache_dir=target_hf_cache
            ).to(self.device)
            self.bigvgan_model.remove_weight_norm()
            self.bigvgan_model.eval()

            # 2. Download/Locate VoiceRestore weights
            print(f"[{self.__class__.__name__}] Fetching VoiceRestore weights via HuggingFace Hub...")
            target_dir = os.path.join(get_engine_base_dir(), "dependencies", "models", "voicerestore")
            os.makedirs(target_dir, exist_ok=True)
            ckpt_path = hf_hub_download(
                repo_id="jadechoghari/VoiceRestore",
                filename="pytorch_model.bin",
                cache_dir=target_dir
            )

            # 3. Init VoiceRestore on the forced inference device
            self.model = OptimizedAudioRestorationModel(
                device=self.device,
                bigvgan_model=self.bigvgan_model
            )
            state_dict = torch.load(ckpt_path, map_location=torch.device(self.device))

            # Unwrap DDP / DataParallel keys if present
            if 'model_state_dict' in state_dict:
                state_dict = state_dict['model_state_dict']
            unwrapped_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

            self.model.voice_restore.load_state_dict(unwrapped_dict, strict=False)
            self.model.eval()
            self.model.to(self.device)
            self._initialized = True
            print(f"[{self.__class__.__name__}] Initialization Complete. (device={self.device})")
        except Exception as e:
            print(f"[{self.__class__.__name__}] Failed to initialize: {e}")
            self.model = None

    def process(self, input_audio_path, noise_profile=None, attenuation_db=None, stage="pre-diffusion"):
        """
        Universal Restoration inference API. Expected sequence:
        Load -> Mono Mixdown -> Flow-matching Inference -> Save
        """
        self._initialize_model()

        output_dir = os.path.join(get_engine_base_dir(), "trinity_temp")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"voicerestore_{stage}_{os.path.basename(input_audio_path)}")

        if not self.model:
            print(f"[{self.__class__.__name__}] Model missing or failed. Skipping restoration (passthrough).")
            return input_audio_path

        print(f"[{self.__class__.__name__}] Running '{stage}' pass (Steps: {self.steps}, CFG: {self.cfg_strength:.1f}) on {self.device}")

        try:
            audio, orig_sr = torchaudio.load(input_audio_path)
            # BigVGAN has hardcoded limits — clamp input audio to safe range
            audio = torch.clamp(audio, -1.0, 1.0)

            # Convert to mono if stereo (VoiceRestore expects mono)
            audio = audio.mean(dim=0, keepdim=True) if audio.dim() > 1 and audio.shape[0] > 1 else audio
            audio = audio.to(self.device)

            with torch.inference_mode():
                restored_wav = self.model(audio, steps=self.steps, cfg_strength=self.cfg_strength)
                restored_wav = restored_wav.squeeze(0).float().cpu()
                restored_wav = torch.clamp(restored_wav, -1.0, 1.0)

            # Ensure at least 2D for torchaudio.save
            if restored_wav.dim() == 1:
                restored_wav = restored_wav.unsqueeze(0)

            torchaudio.save(out_path, restored_wav, self.model.target_sample_rate)
            print(f"[{self.__class__.__name__}] ✓ Restoration saved @ {self.model.target_sample_rate}Hz: {os.path.basename(out_path)}")

        except Exception as e:
            print(f"[{self.__class__.__name__}] Inference Failed: {e}")
            return input_audio_path

        finally:
            self._cleanup()

        return out_path

    def _cleanup(self):
        if self.raw_device == "cuda":
            torch.cuda.empty_cache()
        elif self.raw_device == "mps":
            torch.mps.empty_cache()
        gc.collect()

# Maintain API compatibility with existing pipelines expecting DeepFilterNetWrapper
DeepFilterNetWrapper = VoiceRestoreWrapper


