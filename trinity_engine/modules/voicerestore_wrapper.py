# VOXIS V4.0.0 DENSE — STAGE 3: UNIVERSAL RESTORATION
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# GS-CRYSTAL: Glass Stone Neural Restoration Model (Transformer-Diffusion)
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
from huggingface_hub import hf_hub_download
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir
from .coreml_bridge import CoreMLBridge, CoreMLModule, coreml_viable
from .onnx_bridge import ONNXBridge, ONNXModule, onnx_viable, directml_available
from .adaptive_chunker import AdaptiveChunker

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
    print(f"[GS-CRYSTAL] ImportError: {e}")

class VoiceRestoreWrapper:
    """
    Stage 3 & 5: GS-CRYSTAL Universal Restoration (Transformer-Diffusion).
    Unified 301M parameter flow-matching model for neural audio restoration.

    On Apple Silicon (MPS): runs inference on CPU because BigVGAN uses conv layers
    with output_channels > 65536 which is a hard MPS firmware limit.
    """

    def __init__(self, mode: str = "HIGH", steps_override: int = None, cfg_override: float = None):
        self.mode = mode
        self.raw_device = DeviceOptimizer.get_optimal_device()

        # CoreML bypasses the BigVGAN MPS channel limit — if CoreML is available
        # we can run on the actual device (MPS/Neural Engine) instead of forcing CPU.
        if self.raw_device == "mps" and not coreml_viable():
            self.device = "cpu"
            print("[GS-CRYSTAL] MPS detected — forcing inference to CPU "
                  "(GS-VOCODER channels > 65536 exceed MPS firmware limits)")
        else:
            self.device = self.raw_device
            if coreml_viable():
                print("[GS-CRYSTAL] CoreML available — Neural Engine acceleration enabled")

        self.model = None
        self.bigvgan_model = None
        self._initialized = False

        # CoreML acceleration state (macOS)
        self._coreml_bridge     = CoreMLBridge() if coreml_viable() else None
        self._coreml_full_model = None   # Full VoiceRestore → CoreML MLModel
        self._coreml_enabled    = False  # True once CoreML acceleration is live

        # ONNX/DirectML acceleration state (Windows/Linux/cross-platform)
        self._onnx_bridge       = ONNXBridge() if onnx_viable() else None
        self._onnx_session      = None   # Full model or vocoder ONNX session
        self._onnx_enabled      = False

        # Configure intensity — explicit overrides take priority over mode defaults
        mode_steps = 48 if mode == "EXTREME" else 32
        mode_cfg   = 0.7 if mode == "EXTREME" else 0.65
        self.steps        = steps_override if steps_override is not None else mode_steps
        self.cfg_strength = cfg_override   if cfg_override   is not None else mode_cfg
        self.seed = -1
        self.temperature = 1.0

    def _initialize_model(self):
        if self._initialized:
            return
        print(f"[{self.__class__.__name__}] Initializing GS-CRYSTAL on {self.device}...")

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
            print(f"[{self.__class__.__name__}] Fetching GS-CRYSTAL weights via HuggingFace Hub...")
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

            # Attempt hardware acceleration after successful PyTorch init
            # Priority: CoreML (macOS Neural Engine) → ONNX/DirectML (Windows DX12)
            if coreml_viable():
                self._try_coreml_acceleration()
            elif onnx_viable():
                self._try_onnx_acceleration()

        except Exception as e:
            print(f"[{self.__class__.__name__}] Failed to initialize: {e}")
            self.model = None

    # ── CoreML Acceleration ────────────────────────────────────────────────────

    def _try_coreml_acceleration(self):
        """
        Attempt to convert the GS-CRYSTAL pipeline to CoreML .mlpackage.

        Two-stage strategy:
          1. GS-VOCODER (BigVGAN) — static feedforward graph, highest-impact.
             Solves the MPS channel-limit issue entirely. Neural Engine runs this.
          2. Full GS-CRYSTAL model — bakes in current step/CFG settings.
             Converts the entire flow-matching pass to CoreML.
             Falls back gracefully if the diffusion control-flow can't be traced.
        """
        bridge = self._coreml_bridge
        if bridge is None:
            return

        print("[GS-CRYSTAL] Initializing CoreML acceleration (Glass Stone Neural Engine)...")

        # ── Stage 1: GS-VOCODER (BigVGAN) ────────────────────────────────────
        # BigVGAN input: mel spectrogram (batch=1, n_mels=100, T_mel)
        # BigVGAN output: waveform (batch=1, 1, T_wav) where T_wav = T_mel * 256
        try:
            dummy_mel = torch.zeros(1, 100, 128)   # representative 128 mel frames
            coreml_vocoder = bridge.convert(
                self.bigvgan_model,
                sample_inputs=(dummy_mel,),
                model_name="gs_vocoder_bigvgan_24khz_100band",
                input_names=["mel_spectrogram"],
                output_names=["waveform"],
                dynamic_axes={"mel_spectrogram": [2]},   # T_mel dimension is dynamic
            )
            if coreml_vocoder:
                wrapped_vocoder = CoreMLModule(
                    original=self.bigvgan_model,
                    coreml=coreml_vocoder,
                    input_name="mel_spectrogram",
                    output_name="waveform",
                    bridge=bridge,
                )
                # Patch vocoder reference in wrapper and inside the VoiceRestore model
                self.bigvgan_model = wrapped_vocoder
                for attr in ("bigvgan_model", "vocoder", "bigvgan"):
                    if hasattr(self.model, attr):
                        setattr(self.model, attr, wrapped_vocoder)
                # Also patch inside voice_restore sub-model if present
                vr_sub = getattr(self.model, "voice_restore", None)
                if vr_sub is not None:
                    for attr in ("bigvgan", "vocoder", "bigvgan_model"):
                        if hasattr(vr_sub, attr):
                            setattr(vr_sub, attr, wrapped_vocoder)
                # BigVGAN channel limit no longer applies — restore MPS device
                if str(self.raw_device) == "mps" and self.device == "cpu":
                    self.device = str(self.raw_device)
                    self.model.to(self.device)
                    print("[GS-CRYSTAL] GS-VOCODER on Neural Engine → MPS restored for transformer")
                else:
                    print("[GS-CRYSTAL] ✓ GS-VOCODER running on Neural Engine (CoreML)")
        except Exception as e:
            print(f"[GS-CRYSTAL] GS-VOCODER CoreML conversion skipped: {e}")

        # ── Stage 2: Full GS-CRYSTAL model ───────────────────────────────────
        # Wrap model in a fixed-parameter lambda to bake in step/CFG for tracing.
        # This unrolls the ODE loop into a static graph — valid since steps is
        # fixed at init and never changes per inference call.
        try:
            _steps     = self.steps
            _cfg       = self.cfg_strength
            _seed      = self.seed
            _temp      = self.temperature
            _inner     = self.model

            class _FixedParamWrapper(torch.nn.Module):
                """Bakes diffusion hyperparams in for TorchScript tracing."""
                def __init__(self, m):
                    super().__init__()
                    self.m = m
                def forward(self, x):
                    return self.m(x, steps=_steps, cfg_strength=_cfg,
                                  seed=_seed, temperature=_temp)

            fixed_wrapper = _FixedParamWrapper(_inner).eval()
            # Use 1 second of dummy audio at 24kHz mono
            dummy_audio = torch.zeros(1, 1, 24000).to(self.device)
            coreml_full = bridge.convert(
                fixed_wrapper,
                sample_inputs=(dummy_audio,),
                model_name=f"gs_crystal_full_steps{_steps}",
                input_names=["audio"],
                output_names=["restored_audio"],
                dynamic_axes={"audio": [2]},   # sample dimension is dynamic
            )
            if coreml_full:
                self._coreml_full_model = coreml_full
                self._coreml_enabled    = True
                print(f"[GS-CRYSTAL] ✓ Full GS-CRYSTAL on Neural Engine "
                      f"(steps={_steps}, CFG={_cfg})")
            else:
                print("[GS-CRYSTAL] Full model conversion not available — "
                      "running PyTorch (GS-VOCODER still on Neural Engine)")
        except Exception as e:
            print(f"[GS-CRYSTAL] Full model CoreML skipped: {e}")

    # ── ONNX/DirectML Acceleration ────────────────────────────────────────────

    def _try_onnx_acceleration(self):
        """
        Export GS-VOCODER (BigVGAN) to ONNX for DirectML/CUDA acceleration.

        On Windows: DirectML routes inference to any DirectX 12 GPU (AMD/Intel/NVIDIA).
        On Linux:   CUDAExecutionProvider for NVIDIA GPUs.
        Fallback:   CPUExecutionProvider with ORT graph optimizations (still faster
                    than raw PyTorch CPU due to ONNX operator fusion).
        """
        bridge = self._onnx_bridge
        if bridge is None:
            return

        provider_name = ""
        if directml_available():
            provider_name = "DirectML (DirectX 12 GPU)"
        else:
            from .onnx_bridge import get_provider_name
            provider_name = get_provider_name()

        print(f"[GS-CRYSTAL] Initializing ONNX acceleration → {provider_name}...")

        # ── GS-VOCODER (BigVGAN) → ONNX ──────────────────────────────────────
        try:
            dummy_mel = torch.zeros(1, 100, 128).cpu()
            onnx_session = bridge.export(
                self.bigvgan_model,
                sample_inputs=(dummy_mel,),
                model_name="gs_vocoder_bigvgan_24khz",
                input_names=["mel_spectrogram"],
                output_names=["waveform"],
                dynamic_axes={
                    "mel_spectrogram": {0: "batch", 2: "time"},
                    "waveform":        {0: "batch", 2: "samples"},
                },
            )
            if onnx_session:
                wrapped = ONNXModule(
                    original=self.bigvgan_model,
                    session=onnx_session,
                    input_name="mel_spectrogram",
                    output_name="waveform",
                    bridge=bridge,
                )
                self.bigvgan_model = wrapped
                for attr in ("bigvgan_model", "vocoder", "bigvgan"):
                    if hasattr(self.model, attr):
                        setattr(self.model, attr, wrapped)
                vr_sub = getattr(self.model, "voice_restore", None)
                if vr_sub is not None:
                    for attr in ("bigvgan", "vocoder", "bigvgan_model"):
                        if hasattr(vr_sub, attr):
                            setattr(vr_sub, attr, wrapped)
                self._onnx_session = onnx_session
                self._onnx_enabled = True
                print(f"[GS-CRYSTAL] ✓ GS-VOCODER on {provider_name} (ONNX)")
        except Exception as e:
            print(f"[GS-CRYSTAL] GS-VOCODER ONNX export skipped: {e}")

    # ── Chunked inference settings ─────────────────────────────────────────

    def _infer_chunk(self, chunk_tensor):
        """
        Run GS-CRYSTAL inference on a single chunk.

        Priority:
          1. Full CoreML model (Neural Engine, fastest)
          2. PyTorch model with CoreML-backed BigVGAN vocoder
          3. Pure PyTorch CPU fallback
        """
        # ── Path 1: Full CoreML model ─────────────────────────────────────────
        if self._coreml_enabled and self._coreml_full_model is not None:
            result = self._coreml_bridge.predict_tensor(
                self._coreml_full_model,
                {"audio": chunk_tensor.cpu()},
                "restored_audio",
            )
            if result is not None:
                return torch.clamp(result.squeeze(0).float(), -1.0, 1.0)
            # CoreML inference returned None — fall through to PyTorch
            print("[GS-CRYSTAL] CoreML inference miss — falling back to PyTorch")
            self._coreml_enabled = False

        # ── Path 2 & 3: PyTorch (BigVGAN may still be CoreML-backed) ─────────
        with torch.inference_mode():
            restored = self.model(
                chunk_tensor, steps=self.steps, cfg_strength=self.cfg_strength,
                seed=self.seed, temperature=self.temperature,
            )
            restored = restored.squeeze(0).float().cpu()
            return torch.clamp(restored, -1.0, 1.0)

    def process(self, input_audio_path, noise_profile=None, attenuation_db=None, stage="pre-diffusion"):
        """
        Universal Restoration inference API with automatic chunking via AdaptiveChunker.
        Files are dynamically split into 30s-5m chunks and cached to disk to prevent OOM.
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
            chunker = AdaptiveChunker()
            split_result = chunker.split(input_audio_path)
            out_sr = getattr(self.model, 'target_sample_rate', 24000)

            if not split_result["should_chunk"]:
                # Single pass
                print(f"[{self.__class__.__name__}] Single-pass processing...")
                audio, orig_sr = torchaudio.load(input_audio_path)
                audio = torch.clamp(audio, -1.0, 1.0)
                audio = audio.mean(dim=0, keepdim=True) if audio.dim() > 1 and audio.shape[0] > 1 else audio
                audio = audio.to(self.device)
                
                restored_wav = self._infer_chunk(audio)
                if restored_wav.dim() == 1:
                    restored_wav = restored_wav.unsqueeze(0)
                    
                torchaudio.save(out_path, restored_wav, out_sr)
                print(f"[{self.__class__.__name__}] ✓ Restoration saved @ {out_sr}Hz: {os.path.basename(out_path)}")
                
            else:
                # Chunked pass
                chunk_paths = split_result["chunk_paths"]
                restored_paths = []
                
                for i, c_path in enumerate(chunk_paths):
                    audio, orig_sr = torchaudio.load(c_path)
                    audio = torch.clamp(audio, -1.0, 1.0)
                    audio = audio.mean(dim=0, keepdim=True) if audio.dim() > 1 and audio.shape[0] > 1 else audio
                    audio = audio.to(self.device)
                    
                    restored_wav = self._infer_chunk(audio)
                    if restored_wav.dim() == 1:
                        restored_wav = restored_wav.unsqueeze(0)
                        
                    # Save the processed chunk
                    proc_chunk_path = c_path.replace(".wav", "_proc.wav")
                    torchaudio.save(proc_chunk_path, restored_wav, out_sr)
                    restored_paths.append(proc_chunk_path)
                    
                    del audio
                    del restored_wav
                    self._cleanup()
                
                # Assemble everything seamlessly
                chunker.assemble(restored_paths, out_path, target_sr=out_sr)
                chunker.cleanup()

        except Exception as e:
            print(f"[{self.__class__.__name__}] Inference Failed: {e}")
            return input_audio_path

        finally:
            self._cleanup()

        return out_path

    def _cleanup(self):
        DeviceOptimizer.cleanup_memory()


