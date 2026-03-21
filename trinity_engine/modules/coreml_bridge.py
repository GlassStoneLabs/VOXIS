# VOXIS V4.0.0 DENSE — GS-COREML Acceleration Bridge
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Converts PyTorch models → Apple CoreML .mlpackage for Neural Engine inference.
# Cache: ~/.voxis/coreml/  (one-time conversion, fast on subsequent runs)
# Compute: ComputeUnit.ALL — Neural Engine + GPU + CPU (Apple Silicon optimal)
#
# Integration points:
#   GS-VOCODER  (BigVGAN)          → static graph, ideal for CoreML
#   GS-CRYSTAL  (VoiceRestore)     → full model w/ baked diffusion steps
#   GS-ASCEND   (AudioSR denoiser) → UNet per-step acceleration

import os
import platform
import hashlib
import torch
import numpy as np

from .path_utils import get_engine_base_dir

# ── Availability ──────────────────────────────────────────────────────────────

IS_APPLE_SILICON = (
    platform.system() == "Darwin" and platform.machine() == "arm64"
)

COREML_AVAILABLE = False
ct = None
try:
    import coremltools as ct           # type: ignore
    COREML_AVAILABLE = True
except ImportError:
    pass


def coreml_viable() -> bool:
    """Returns True only on macOS arm64 with coremltools installed."""
    return IS_APPLE_SILICON and COREML_AVAILABLE


# ── Bridge ────────────────────────────────────────────────────────────────────

class CoreMLBridge:
    """
    Glass Stone CoreML acceleration bridge.

    Convert  → torch.jit.trace + coremltools.convert() → .mlpackage
    Cache    → ~/.voxis/coreml/<name>_<weighthash>.mlpackage
    Load     → ct.models.MLModel(compute_units=ALL)
    Predict  → tensor → numpy → CoreML → numpy → tensor

    All operations are wrapped in try/except so any failure transparently
    falls back to the existing PyTorch inference path.
    """

    def __init__(self):
        base_dir = get_engine_base_dir()
        self.cache_dir = os.path.join(base_dir, "coreml")
        os.makedirs(self.cache_dir, exist_ok=True)

    # ── Conversion ────────────────────────────────────────────────────────────

    def convert(
        self,
        torch_model: "torch.nn.Module",
        sample_inputs: tuple,
        model_name: str,
        input_names: list,
        output_names: list,
        dynamic_axes: dict = None,
        force_recompute: bool = False,
    ) -> "ct.models.MLModel | None":
        """
        Trace a PyTorch model and convert to CoreML .mlpackage.

        Args:
            torch_model:    nn.Module in eval() mode (CPU tensors)
            sample_inputs:  Tuple of representative CPU tensors
            model_name:     Cache key prefix (e.g. "gs_vocoder_bigvgan")
            input_names:    CoreML input tensor names (one per sample input)
            output_names:   CoreML output names (informational only)
            dynamic_axes:   {input_name: [dim_indices]} for RangeDim support
                            e.g. {"mel": [2]} makes the time dim dynamic
            force_recompute: Ignore cache and reconvert

        Returns:
            Loaded MLModel with ComputeUnit.ALL, or None on failure.
        """
        if not coreml_viable():
            return None

        weights_hash = self._hash_model(torch_model)
        pkg_path = os.path.join(self.cache_dir, f"{model_name}_{weights_hash[:10]}.mlpackage")

        if not force_recompute and os.path.exists(pkg_path):
            print(f"[CoreMLBridge] Cache hit → {model_name} (skipping conversion)")
            return self._load_package(pkg_path)

        print(f"[CoreMLBridge] Converting {model_name} to CoreML (one-time ~30–90s)...")

        try:
            torch_model.eval()
            sample_cpu = tuple(
                t.detach().cpu().float() if isinstance(t, torch.Tensor) else t
                for t in (sample_inputs if isinstance(sample_inputs, (list, tuple)) else (sample_inputs,))
            )

            with torch.no_grad():
                traced = torch.jit.trace(torch_model, sample_cpu, strict=False)

            # Build CoreML input specs with optional dynamic dimensions
            ct_inputs = []
            for name, sample in zip(input_names, sample_cpu):
                if not isinstance(sample, torch.Tensor):
                    continue
                shape = list(sample.shape)
                if dynamic_axes and name in dynamic_axes:
                    for dim_idx in dynamic_axes[name]:
                        shape[dim_idx] = ct.RangeDim(minimum=1, maximum=65536)
                ct_inputs.append(ct.TensorType(name=name, shape=shape, dtype=float))

            # macOS 14+ unlocks newer ANE ops (e.g. grouped conv, attention);
            # fall back to macOS 13 if the host is older.
            import platform
            ver = tuple(int(x) for x in platform.mac_ver()[0].split(".")[:2]) if platform.system() == "Darwin" else (0, 0)
            deploy_target = ct.target.macOS14 if ver >= (14, 0) else ct.target.macOS13

            mlmodel = ct.convert(
                traced,
                inputs=ct_inputs,
                convert_to="mlprogram",
                compute_precision=ct.precision.FLOAT16,
                minimum_deployment_target=deploy_target,
            )

            mlmodel.short_description = f"Glass Stone Labs — {model_name}"
            mlmodel.author = "Glass Stone LLC — CEO: Gabriel B. Rodriguez"
            mlmodel.save(pkg_path)
            print(f"[CoreMLBridge] ✓ {model_name} saved → {pkg_path}")
            return self._load_package(pkg_path)

        except Exception as e:
            print(f"[CoreMLBridge] Conversion failed ({model_name}): {e}")
            self._cleanup_partial(pkg_path)
            return None

    def _load_package(self, pkg_path: str) -> "ct.models.MLModel | None":
        """
        Load .mlpackage with optimal ComputeUnit for Apple Silicon.

        Priority strategy:
          1. CPU_AND_NEURAL_ENGINE — routes compute to the ANE (NPU) with CPU
             fallback for ops the ANE doesn't support. Avoids GPU contention
             so PyTorch can keep MPS for stages that need it.
          2. ALL — Neural Engine + GPU + CPU (if ANE-only fails).
          3. CPU_AND_GPU — last resort if ANE isn't compatible.
        """
        if not COREML_AVAILABLE:
            return None

        # Try compute unit tiers from most to least optimal
        compute_tiers = [
            (ct.ComputeUnit.CPU_AND_NEURAL_ENGINE, "CPU + Neural Engine (ANE/NPU)"),
            (ct.ComputeUnit.ALL,                   "ALL (ANE + GPU + CPU)"),
            (ct.ComputeUnit.CPU_AND_GPU,            "CPU + GPU"),
        ]
        for unit, label in compute_tiers:
            try:
                model = ct.models.MLModel(pkg_path, compute_units=unit)
                print(f"[CoreMLBridge] ✓ Loaded — {label}")
                return model
            except Exception as e:
                print(f"[CoreMLBridge] {label} failed: {e}")
                continue

        print(f"[CoreMLBridge] All compute tiers failed for {pkg_path}")
        return None

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(self, coreml_model, input_dict: dict) -> dict:
        """
        Run CoreML inference.
        Converts torch.Tensor / numpy inputs → float32 numpy for CoreML,
        returns raw dict output (numpy arrays).
        """
        np_inputs = {}
        for k, v in input_dict.items():
            if isinstance(v, torch.Tensor):
                np_inputs[k] = v.detach().cpu().to(torch.float32).numpy()
            elif isinstance(v, np.ndarray):
                np_inputs[k] = v.astype(np.float32)
            else:
                np_inputs[k] = v
        return coreml_model.predict(np_inputs)

    def predict_tensor(
        self,
        coreml_model,
        input_dict: dict,
        output_key: str,
        target_device: str = "cpu",
    ) -> "torch.Tensor | None":
        """
        predict() → single tensor output on target_device.
        Returns None on failure (caller should fall back to PyTorch).
        """
        try:
            result = self.predict(coreml_model, input_dict)
            arr = result.get(output_key)
            if arr is None:
                # Try first available key
                arr = next(iter(result.values()))
            tensor = torch.from_numpy(np.array(arr)).float()
            if target_device != "cpu":
                tensor = tensor.to(target_device)
            return tensor
        except Exception as e:
            print(f"[CoreMLBridge] Inference error: {e}")
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _hash_model(model: "torch.nn.Module") -> str:
        """
        SHA-256 fingerprint of model weights for cache invalidation.
        Samples first 256 bytes per parameter to stay fast on large models.
        """
        h = hashlib.sha256()
        try:
            for name, param in model.named_parameters():
                h.update(name.encode())
                data = param.data.detach().cpu().float().numpy()
                h.update(data.tobytes()[:256])
        except Exception:
            h.update(b"gs-coreml-fallback")
        return h.hexdigest()

    @staticmethod
    def _cleanup_partial(path: str):
        if os.path.exists(path):
            import shutil
            try:
                shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            except Exception:
                pass

    @staticmethod
    def is_available() -> bool:
        """True if CoreML acceleration can be used on this machine."""
        return coreml_viable()


# ── CoreML Module Wrapper ─────────────────────────────────────────────────────

class CoreMLModule:
    """
    Drop-in replacement for a torch.nn.Module that routes __call__() through
    a CoreML MLModel for Neural Engine execution.

    Falls back to the original PyTorch module after 3 consecutive CoreML
    inference failures to guarantee pipeline continuity.

    Usage:
        wrapped = CoreMLModule(
            original=bigvgan_model,
            coreml=loaded_mlmodel,
            input_name="mel_spectrogram",
            output_name="waveform",
        )
        output = wrapped(mel_tensor)   # transparent, works like nn.Module
    """

    def __init__(
        self,
        original: "torch.nn.Module",
        coreml: "ct.models.MLModel",
        input_name: str,
        output_name: str,
        bridge: CoreMLBridge = None,
    ):
        self.original    = original
        self.coreml      = coreml
        self.input_name  = input_name
        self.output_name = output_name
        self.bridge      = bridge or CoreMLBridge()
        self._failures   = 0
        self._MAX_FAIL   = 3

    def __call__(self, *args, **kwargs):
        if self.coreml is not None and self._failures < self._MAX_FAIL:
            try:
                primary = args[0]
                result = self.bridge.predict_tensor(
                    self.coreml,
                    {self.input_name: primary},
                    self.output_name,
                )
                if result is not None:
                    return result
            except Exception as e:
                self._failures += 1
                print(f"[CoreMLModule] Neural Engine miss ({self._failures}/{self._MAX_FAIL}): {e}")
                if self._failures >= self._MAX_FAIL:
                    print("[CoreMLModule] Falling back permanently to PyTorch.")
        # PyTorch fallback — transparent to caller
        return self.original(*args, **kwargs)

    # Forward common nn.Module methods so wrapper is transparent
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
