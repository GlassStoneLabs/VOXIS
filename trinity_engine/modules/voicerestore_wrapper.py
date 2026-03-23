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

    def __init__(self, mode: str = "HIGH", steps_override: int = None, cfg_override: float = None, temp_manager=None):
        self.mode = mode
        self.raw_device = DeviceOptimizer.get_optimal_device()
        self._temp_manager = temp_manager

        # VoiceRestore transformer IS MPS-friendly (FP16 on Apple Silicon).
        # Only BigVGAN vocoder has the MPS channel limit (>65536).
        # Strategy: run transformer on MPS, BigVGAN on CoreML Neural Engine or CPU.
        if str(self.raw_device) == "mps":
            if coreml_viable():
                # CoreML will handle BigVGAN → transformer runs on MPS
                self.device = "mps"
                print("[GS-CRYSTAL] CoreML available — transformer on MPS, vocoder on Neural Engine")
            else:
                # No CoreML → must force everything to CPU (BigVGAN can't run on MPS)
                self.device = "cpu"
                print("[GS-CRYSTAL] MPS detected — forcing inference to CPU "
                      "(GS-VOCODER channels > 65536 exceed MPS firmware limits)")
        else:
            self.device = self.raw_device

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
        # CFG tuned down to reduce hallucination artifacts while preserving restoration
        # Temperature lowered from 1.0 to reduce stochastic noise in diffusion outputs
        mode_steps = 48 if mode == "EXTREME" else 32
        mode_cfg   = 0.65 if mode == "EXTREME" else 0.50
        self.steps        = steps_override if steps_override is not None else mode_steps
        self.cfg_strength = cfg_override   if cfg_override   is not None else mode_cfg
        self.seed = -1
        self.temperature = 0.85

    def _initialize_model(self):
        if self._initialized:
            return
        print(f"[{self.__class__.__name__}] Initializing GS-CRYSTAL on {self.device}...")

        try:
            # 1. Init BigVGAN vocoder on the forced inference device (CPU for MPS hosts)
            
            # Map PyInstaller local payloads for BigVGAN's huggingface downloader logic
            target_hf_cache = os.path.join(get_engine_base_dir(), "dependencies", "models", "huggingface")
            os.environ["HUGGINGFACE_HUB_CACHE"] = target_hf_cache
            
            # Load to CPU first, move to device after full init to avoid
            # duplicate GPU copies during CoreML/ONNX conversion probing
            self.bigvgan_model = bigvgan.BigVGAN.from_pretrained(
                'nvidia/bigvgan_v2_24khz_100band_256x',
                use_cuda_kernel=False,
                cache_dir=target_hf_cache
            )
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
            # Load state_dict to CPU first, then move model to device once —
            # avoids holding duplicate copies on both CPU and device
            state_dict = torch.load(ckpt_path, map_location="cpu")

            # Unwrap DDP / DataParallel keys if present
            if 'model_state_dict' in state_dict:
                state_dict = state_dict['model_state_dict']
            unwrapped_dict = {k.replace('module.', ''): v for k, v in state_dict.items()}

            self.model.voice_restore.load_state_dict(unwrapped_dict, strict=False)
            del state_dict, unwrapped_dict  # Free CPU copies
            self.model.eval()
            self.model.to(self.device)
            self._initialized = True
            print(f"[{self.__class__.__name__}] Initialization Complete. (device={self.device})")

            # Attempt torch.compile for fused graph execution (PyTorch 2.0+)
            # CUDA: inductor backend. EXTREME+MPS: aot_eager backend (graph fusion without inductor).
            extreme = os.environ.get("VOXIS_EXTREME_ACCEL") == "1"
            if hasattr(torch, 'compile'):
                if str(self.device).startswith('cuda'):
                    try:
                        self.model = torch.compile(self.model, mode='reduce-overhead')
                        print(f"[{self.__class__.__name__}] torch.compile active (CUDA inductor)")
                    except Exception as compile_err:
                        print(f"[{self.__class__.__name__}] torch.compile skipped: {compile_err}")
                elif extreme and str(self.device) == 'mps':
                    try:
                        self.model = torch.compile(self.model, backend='aot_eager')
                        print(f"[{self.__class__.__name__}] torch.compile active (MPS aot_eager — EXTREME)")
                    except Exception as compile_err:
                        print(f"[{self.__class__.__name__}] torch.compile (MPS) skipped: {compile_err}")

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
                print("[GS-CRYSTAL] [OK] GS-VOCODER running on Neural Engine (CoreML)")
                # If we were on CPU and CoreML vocoder succeeded, promote to MPS
                if str(self.raw_device) == "mps" and str(self.device) == "cpu":
                    self.device = "mps"
                    self.model.to(self.device)
                    print("[GS-CRYSTAL] Transformer promoted to MPS (vocoder on Neural Engine)")
        except Exception as e:
            print(f"[GS-CRYSTAL] GS-VOCODER CoreML conversion skipped: {e}")
            # CoreML vocoder failed — BigVGAN can't run on MPS, fall back to CPU
            if str(self.raw_device) == "mps" and str(self.device) == "mps":
                self.device = "cpu"
                self.model.to("cpu")
                self.bigvgan_model.to("cpu")
                print("[GS-CRYSTAL] Falling back to CPU (vocoder CoreML unavailable)")

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
                print(f"[GS-CRYSTAL] [OK] Full GS-CRYSTAL on Neural Engine "
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
                print(f"[GS-CRYSTAL] [OK] GS-VOCODER on {provider_name} (ONNX)")
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

        if self._temp_manager:
            output_dir = self._temp_manager.get_stage_dir("denoise")
        else:
            output_dir = os.path.join(get_engine_base_dir(), "trinity_temp")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"voicerestore_{stage}_{os.path.basename(input_audio_path)}")

        if not self.model:
            print(f"[{self.__class__.__name__}] Model missing or failed. Skipping restoration (passthrough).")
            return input_audio_path

        print(f"[{self.__class__.__name__}] Running '{stage}' pass (Steps: {self.steps}, CFG: {self.cfg_strength:.1f}) on {self.device}")

        try:
            out_sr = getattr(self.model, 'target_sample_rate', 24000)

            # VoiceRestore's transformer has max_seq_len=2000 mel frames.
            # BigVGAN hop_length=256, sample_rate=24kHz → 2000*256/24000 ≈ 21.3s max.
            # Chunk at 15s with 2s overlap — larger chunks = fewer overlaps = less RAM.
            MAX_CHUNK_SEC = 15
            OVERLAP_SEC = 2

            audio_full, orig_sr = torchaudio.load(input_audio_path)
            audio_full = torch.clamp(audio_full, -1.0, 1.0)
            # Mix to mono (VoiceRestore expects mono)
            if audio_full.dim() > 1 and audio_full.shape[0] > 1:
                audio_full = audio_full.mean(dim=0, keepdim=True)

            duration_sec = audio_full.shape[-1] / orig_sr

            if duration_sec <= MAX_CHUNK_SEC:
                # Single pass — fits within model's sequence limit
                print(f"[{self.__class__.__name__}] Single-pass processing ({duration_sec:.1f}s)...")
                audio = audio_full.to(self.device)
                del audio_full
                restored_wav = self._infer_chunk(audio)
                del audio
                if restored_wav.dim() == 1:
                    restored_wav = restored_wav.unsqueeze(0)
                torchaudio.save(out_path, restored_wav.cpu(), out_sr)
                del restored_wav
                print(f"[{self.__class__.__name__}] [OK] Restoration saved @ {out_sr}Hz: {os.path.basename(out_path)}")
            else:
                # Chunked pass — stream each chunk to disk to avoid accumulating in RAM
                chunk_samples = int(MAX_CHUNK_SEC * orig_sr)
                overlap_samples = int(OVERLAP_SEC * orig_sr)
                stride_samples = chunk_samples - overlap_samples
                total_samples = audio_full.shape[-1]
                import math as _math
                num_chunks = max(1, _math.ceil((total_samples - overlap_samples) / stride_samples))

                print(f"[{self.__class__.__name__}] Chunking {duration_sec:.1f}s → {num_chunks} segments "
                      f"({MAX_CHUNK_SEC}s each, {OVERLAP_SEC}s overlap)")

                # Write each restored chunk to a temp file instead of holding all in RAM
                chunk_temp_dir = os.path.join(os.path.dirname(out_path), "_vr_chunks")
                os.makedirs(chunk_temp_dir, exist_ok=True)
                chunk_paths = []

                for i in range(num_chunks):
                    start = i * stride_samples
                    end = min(start + chunk_samples, total_samples)
                    chunk = audio_full[:, start:end].to(self.device)

                    print(f"[{self.__class__.__name__}] Chunk {i+1}/{num_chunks}: "
                          f"{start/orig_sr:.1f}s–{end/orig_sr:.1f}s ({(end-start)/orig_sr:.1f}s)")

                    restored_wav = self._infer_chunk(chunk)
                    del chunk
                    if restored_wav.dim() == 1:
                        restored_wav = restored_wav.unsqueeze(0)

                    # Save to disk immediately, free RAM
                    chunk_path = os.path.join(chunk_temp_dir, f"vr_chunk_{i:04d}.wav")
                    torchaudio.save(chunk_path, restored_wav.cpu(), out_sr)
                    chunk_paths.append(chunk_path)
                    del restored_wav
                    self._cleanup()

                del audio_full

                # Reassemble with equal-power cosine crossfade — prevents phase
                # cancellation artifacts at chunk boundaries (linear fade causes
                # energy dips; cosine preserves constant power across the stitch)
                overlap_out = int(OVERLAP_SEC * out_sr)
                assembled = torchaudio.load(chunk_paths[0])[0]

                # Apply micro-fade (2ms) at chunk tail to kill DC offset clicks
                micro_fade_samples = max(1, int(0.002 * out_sr))

                # Cache fade curves to avoid recreating per-stitch
                _fade_out = None
                _fade_in = None

                for i in range(1, len(chunk_paths)):
                    right = torchaudio.load(chunk_paths[i])[0]
                    ov = min(overlap_out, assembled.shape[-1], right.shape[-1])
                    if ov > 0:
                        if _fade_out is None or _fade_out.shape[0] != ov:
                            # Equal-power cosine crossfade: cos²(t) + sin²(t) = 1
                            t = torch.linspace(0.0, torch.pi / 2, ov)
                            _fade_out = torch.cos(t)   # 1 → 0 (equal-power)
                            _fade_in  = torch.sin(t)    # 0 → 1 (equal-power)
                        blended = assembled[..., -ov:] * _fade_out + right[..., :ov] * _fade_in
                        assembled = torch.cat([assembled[..., :-ov], blended, right[..., ov:]], dim=-1)
                    else:
                        # No overlap — apply micro-fade to prevent click at boundary
                        mf = min(micro_fade_samples, assembled.shape[-1], right.shape[-1])
                        assembled[..., -mf:] *= torch.linspace(1.0, 0.0, mf)
                        right[..., :mf] *= torch.linspace(0.0, 1.0, mf)
                        assembled = torch.cat([assembled, right], dim=-1)
                    del right

                # Normalize if needed (in-place)
                peak = assembled.abs().max()
                if peak > 1.0:
                    assembled.div_(peak)

                torchaudio.save(out_path, assembled, out_sr)
                del assembled
                print(f"[{self.__class__.__name__}] [OK] Restoration saved @ {out_sr}Hz: {os.path.basename(out_path)}")

                # Clean up chunk temp files
                import shutil
                shutil.rmtree(chunk_temp_dir, ignore_errors=True)

        except Exception as e:
            print(f"[{self.__class__.__name__}] Inference Failed: {e}")
            return input_audio_path

        finally:
            self._cleanup()

        return out_path

    def _cleanup(self):
        DeviceOptimizer.cleanup_memory()


