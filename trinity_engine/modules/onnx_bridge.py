# VOXIS V4.0.0 DENSE — GS-ONNX Cross-Platform Acceleration Bridge
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Exports PyTorch models → ONNX format for hardware-accelerated inference.
# Cache: ~/.voxis/onnx/  (one-time export, fast on subsequent runs)
#
# Execution Provider priority (resolved at runtime):
#   Windows:  DmlExecutionProvider (DirectML → any DirectX 12 GPU: AMD/Intel/NVIDIA)
#           → CUDAExecutionProvider (NVIDIA CUDA)
#           → CPUExecutionProvider
#   macOS:    CoreMLExecutionProvider (Neural Engine + GPU)
#           → CPUExecutionProvider
#   Linux:    CUDAExecutionProvider
#           → CPUExecutionProvider
#
# Integration points:
#   GS-VOCODER  (BigVGAN)          → static graph, ideal for ONNX
#   GS-CRYSTAL  (VoiceRestore)     → per-step denoiser export
#   GS-ASCEND   (AudioSR denoiser) → UNet per-step acceleration
#   GS-PRISM    (audio-separator)  → already uses onnxruntime providers

import os
import sys
import platform
import hashlib
import torch
import numpy as np

from .path_utils import get_engine_base_dir

# ── Availability ──────────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS   = platform.system() == "Darwin"
IS_LINUX   = platform.system() == "Linux"

ORT_AVAILABLE = False
try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
except ImportError:
    ort = None

ONNX_AVAILABLE = False
try:
    import onnx
    ONNX_AVAILABLE = True
except ImportError:
    onnx = None


def _resolve_providers() -> list:
    """
    Resolve the best available ONNX Runtime execution providers for this platform.
    Returns a priority-ordered list.
    """
    if not ORT_AVAILABLE:
        return []

    available = ort.get_available_providers()
    providers = []

    # Windows: DirectML first (any DX12 GPU — AMD, Intel, NVIDIA)
    if IS_WINDOWS and "DmlExecutionProvider" in available:
        providers.append("DmlExecutionProvider")

    # NVIDIA CUDA (all platforms)
    if "CUDAExecutionProvider" in available:
        providers.append("CUDAExecutionProvider")

    # macOS: CoreML (Neural Engine + GPU)
    if IS_MACOS and "CoreMLExecutionProvider" in available:
        providers.append("CoreMLExecutionProvider")

    # CPU is always the final fallback
    if "CPUExecutionProvider" in available:
        providers.append("CPUExecutionProvider")

    return providers


def onnx_viable() -> bool:
    """True if ONNX export + runtime inference is possible on this machine."""
    return ORT_AVAILABLE


def directml_available() -> bool:
    """True if DirectML (Windows DirectX 12 GPU) acceleration is available."""
    if not ORT_AVAILABLE or not IS_WINDOWS:
        return False
    return "DmlExecutionProvider" in ort.get_available_providers()


def get_provider_name() -> str:
    """Human-readable name of the active acceleration provider."""
    providers = _resolve_providers()
    if not providers:
        return "CPU (no ONNX Runtime)"
    primary = providers[0]
    labels = {
        "DmlExecutionProvider":    "DirectML (DirectX 12 GPU)",
        "CUDAExecutionProvider":   "CUDA (NVIDIA GPU)",
        "CoreMLExecutionProvider": "CoreML (Neural Engine)",
        "CPUExecutionProvider":    "CPU",
    }
    return labels.get(primary, primary)


# ── ONNX Bridge ──────────────────────────────────────────────────────────────

class ONNXBridge:
    """
    Glass Stone ONNX acceleration bridge.

    Export   → torch.onnx.export() → .onnx file with opset 17
    Optimize → onnxruntime graph optimization (ORT_ENABLE_ALL)
    Cache    → ~/.voxis/onnx/<name>_<hash>.onnx
    Infer    → ort.InferenceSession with best provider

    Works on all platforms. Windows uses DirectML for GPU acceleration
    on AMD, Intel, and NVIDIA GPUs via DirectX 12.
    """

    def __init__(self):
        base_dir = get_engine_base_dir()
        self.cache_dir = os.path.join(base_dir, "onnx")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.providers = _resolve_providers()

    # ── Export ─────────────────────────────────────────────────────────────────

    def export(
        self,
        torch_model: "torch.nn.Module",
        sample_inputs: tuple,
        model_name: str,
        input_names: list,
        output_names: list,
        dynamic_axes: dict = None,
        opset_version: int = 17,
        force_reexport: bool = False,
    ) -> "ort.InferenceSession | None":
        """
        Export a PyTorch model to ONNX and return an InferenceSession.

        Args:
            torch_model:    nn.Module in eval() mode
            sample_inputs:  Tuple of representative CPU tensors
            model_name:     Cache key (e.g. "gs_vocoder_bigvgan")
            input_names:    ONNX graph input names
            output_names:   ONNX graph output names
            dynamic_axes:   {name: {dim_idx: "dim_name"}} for dynamic shapes
                            e.g. {"mel": {2: "time"}} makes dim 2 dynamic
            opset_version:  ONNX opset (17 is widely supported)
            force_reexport: Skip cache and re-export

        Returns:
            ort.InferenceSession ready for inference, or None on failure.
        """
        if not ORT_AVAILABLE:
            return None

        weights_hash = self._hash_model(torch_model)
        onnx_path = os.path.join(self.cache_dir, f"{model_name}_{weights_hash[:10]}.onnx")

        if not force_reexport and os.path.exists(onnx_path):
            print(f"[ONNXBridge] Cache hit → {model_name}")
            return self._load_session(onnx_path)

        print(f"[ONNXBridge] Exporting {model_name} to ONNX (one-time ~15–60s)...")

        try:
            torch_model.eval()
            sample_cpu = tuple(
                t.detach().cpu().float() if isinstance(t, torch.Tensor) else t
                for t in (sample_inputs if isinstance(sample_inputs, (list, tuple)) else (sample_inputs,))
            )

            # Build dynamic_axes dict for torch.onnx.export
            onnx_dynamic_axes = {}
            if dynamic_axes:
                onnx_dynamic_axes = dynamic_axes

            with torch.no_grad():
                torch.onnx.export(
                    torch_model,
                    sample_cpu if len(sample_cpu) > 1 else sample_cpu[0],
                    onnx_path,
                    input_names=input_names,
                    output_names=output_names,
                    dynamic_axes=onnx_dynamic_axes,
                    opset_version=opset_version,
                    do_constant_folding=True,
                    export_params=True,
                )

            # Validate exported model
            if ONNX_AVAILABLE:
                model_proto = onnx.load(onnx_path)
                onnx.checker.check_model(model_proto, full_check=True)
                print(f"[ONNXBridge] ✓ ONNX validation passed")

            print(f"[ONNXBridge] ✓ {model_name} exported → {onnx_path} "
                  f"({os.path.getsize(onnx_path) / 1024 / 1024:.1f} MB)")

            return self._load_session(onnx_path)

        except Exception as e:
            print(f"[ONNXBridge] Export failed ({model_name}): {e}")
            self._cleanup_partial(onnx_path)
            return None

    def _load_session(self, onnx_path: str) -> "ort.InferenceSession | None":
        """
        Load an ONNX model as an InferenceSession with the best provider.
        Applies graph optimizations for maximum throughput.
        """
        if not ORT_AVAILABLE:
            return None

        try:
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            # Enable memory optimization
            sess_options.enable_mem_pattern = True
            sess_options.enable_cpu_mem_arena = True

            session = ort.InferenceSession(
                onnx_path,
                sess_options=sess_options,
                providers=self.providers,
            )

            active_provider = session.get_providers()[0] if session.get_providers() else "unknown"
            provider_label = {
                "DmlExecutionProvider":    "DirectML (DirectX 12 GPU)",
                "CUDAExecutionProvider":   "CUDA (NVIDIA GPU)",
                "CoreMLExecutionProvider": "CoreML (Neural Engine)",
                "CPUExecutionProvider":    "CPU",
            }.get(active_provider, active_provider)

            print(f"[ONNXBridge] ✓ Session loaded — provider: {provider_label}")
            return session

        except Exception as e:
            print(f"[ONNXBridge] Session load failed: {e}")
            return None

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(self, session: "ort.InferenceSession", input_dict: dict) -> dict:
        """
        Run ONNX inference.
        Converts torch.Tensor inputs to numpy float32.
        Returns dict of {output_name: numpy_array}.
        """
        np_inputs = {}
        for k, v in input_dict.items():
            if isinstance(v, torch.Tensor):
                np_inputs[k] = v.detach().cpu().to(torch.float32).numpy()
            elif isinstance(v, np.ndarray):
                np_inputs[k] = v.astype(np.float32)
            else:
                np_inputs[k] = v

        output_names = [out.name for out in session.get_outputs()]
        results = session.run(output_names, np_inputs)
        return dict(zip(output_names, results))

    def predict_tensor(
        self,
        session: "ort.InferenceSession",
        input_dict: dict,
        output_key: str = None,
        target_device: str = "cpu",
    ) -> "torch.Tensor | None":
        """
        predict() → single tensor output on target_device.
        If output_key is None, returns the first output.
        Returns None on failure.
        """
        try:
            result = self.predict(session, input_dict)
            if output_key and output_key in result:
                arr = result[output_key]
            else:
                arr = next(iter(result.values()))
            tensor = torch.from_numpy(np.array(arr)).float()
            if target_device != "cpu":
                tensor = tensor.to(target_device)
            return tensor
        except Exception as e:
            print(f"[ONNXBridge] Inference error: {e}")
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _hash_model(model: "torch.nn.Module") -> str:
        """SHA-256 fingerprint of model weights for cache invalidation."""
        h = hashlib.sha256()
        try:
            for name, param in model.named_parameters():
                h.update(name.encode())
                data = param.data.detach().cpu().float().numpy()
                h.update(data.tobytes()[:256])
        except Exception:
            h.update(b"gs-onnx-fallback")
        return h.hexdigest()

    @staticmethod
    def _cleanup_partial(path: str):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    @staticmethod
    def is_available() -> bool:
        return onnx_viable()

    @staticmethod
    def get_providers() -> list:
        return _resolve_providers()


# ── ONNX Module Wrapper ──────────────────────────────────────────────────────

class ONNXModule:
    """
    Drop-in replacement for a torch.nn.Module that routes __call__()
    through an ONNX Runtime InferenceSession.

    On Windows, this uses DirectML for GPU acceleration on any DirectX 12 GPU.
    On macOS, this uses CoreMLExecutionProvider.
    On Linux/NVIDIA, this uses CUDAExecutionProvider.

    Falls back to the original PyTorch module after 3 consecutive ONNX
    inference failures to guarantee pipeline continuity.

    Usage:
        wrapped = ONNXModule(
            original=bigvgan_model,
            session=loaded_ort_session,
            input_name="mel_spectrogram",
            output_name="waveform",
        )
        output = wrapped(mel_tensor)   # transparent
    """

    def __init__(
        self,
        original: "torch.nn.Module",
        session: "ort.InferenceSession",
        input_name: str,
        output_name: str,
        bridge: ONNXBridge = None,
    ):
        self.original    = original
        self.session     = session
        self.input_name  = input_name
        self.output_name = output_name
        self.bridge      = bridge or ONNXBridge()
        self._failures   = 0
        self._MAX_FAIL   = 3

    def __call__(self, *args, **kwargs):
        if self.session is not None and self._failures < self._MAX_FAIL:
            try:
                primary = args[0]
                result = self.bridge.predict_tensor(
                    self.session,
                    {self.input_name: primary},
                    self.output_name,
                )
                if result is not None:
                    return result
            except Exception as e:
                self._failures += 1
                print(f"[ONNXModule] Inference miss ({self._failures}/{self._MAX_FAIL}): {e}")
                if self._failures >= self._MAX_FAIL:
                    print("[ONNXModule] Falling back permanently to PyTorch.")
        return self.original(*args, **kwargs)

    def eval(self):
        if hasattr(self.original, 'eval'):
            self.original.eval()
        return self

    def to(self, device):
        if hasattr(self.original, 'to'):
            self.original = self.original.to(device)
        return self

    def remove_weight_norm(self):
        if hasattr(self.original, 'remove_weight_norm'):
            self.original.remove_weight_norm()
        return self

    def parameters(self):
        return self.original.parameters() if hasattr(self.original, 'parameters') else iter([])

    def named_parameters(self):
        return self.original.named_parameters() if hasattr(self.original, 'named_parameters') else iter([])
