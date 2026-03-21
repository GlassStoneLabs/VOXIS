# VOXIS V4.0.0 DENSE — STAGE 2: SOURCE SEPARATION
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# GS-PRISM: Glass Stone Voice Isolation Model via audio-separator.
# Features:
#   - Cross-platform device selection (CUDA → MPS → CPU)
#   - Memory-aware batch sizing
#   - Automatic model download on first run
#   - Output validation (file existence + minimum size)
#   - Graceful fallback on failure

import os
import sys
import gc
import logging
import torch
import warnings
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir
from .coreml_bridge import coreml_viable, IS_APPLE_SILICON

# Suppress noisy warnings from audio-separator internals
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Try to import audio-separator
try:
    from audio_separator.separator import Separator
    SEPARATOR_AVAILABLE = True
except ImportError:
    SEPARATOR_AVAILABLE = False


# ── Constants ────────────────────────────────────────────────────────────────

# Primary model: BS-RoFormer (highest quality vocal isolation)
PRIMARY_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
# Fallback model: MDX23C (faster, smaller, still good quality)
FALLBACK_MODEL = "MDX23C-8KFFT-InstVoc_HQ.ckpt"


class GlassStoneSeparator:
    """
    Stage 2: Source Separation using BS-RoFormer via audio-separator.
    Isolates vocals from instruments for targeted restoration.
    """

    def __init__(self, device=None):
        self.device = device or DeviceOptimizer.get_optimal_device()
        self.device_str = DeviceOptimizer.get_device_string()
        self.separator = None
        self.model_loaded = False

        # On Apple Silicon, prefer CoreML-accelerated ONNX runtime for MDX/VR fallback models.
        # BS-RoFormer (primary) uses PyTorch directly — device_str routes it to MPS.
        self._ort_providers = self._resolve_ort_providers()

        # Resolve paths relative to this script or Tauri resources
        base_dir = get_engine_base_dir()
        self.model_dir = os.path.join(base_dir, "dependencies", "models", "audio_separator")
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        print(f"[{self.__class__.__name__}] Device: {self.device_str.upper()}")
        print(f"[{self.__class__.__name__}] Model dir: {self.model_dir}")

        if not SEPARATOR_AVAILABLE:
            print(f"[{self.__class__.__name__}] ⚠ audio-separator not installed. "
                  f"Install with: pip install audio-separator[cpu]")
            return

        # Initialize separator
        self._init_separator(PRIMARY_MODEL)

    @staticmethod
    def _resolve_ort_providers() -> list:
        """
        Return the best available ONNX Runtime execution providers.
        Priority: CoreMLExecutionProvider → CPUExecutionProvider.
        Used by audio-separator for MDX/VR model ONNX inference.
        """
        try:
            import onnxruntime as ort
            available = ort.get_available_providers()
            if IS_APPLE_SILICON and "CoreMLExecutionProvider" in available:
                print("[GS-PRISM] ONNX Runtime: CoreML execution provider active")
                return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
            return ["CPUExecutionProvider"]
        except ImportError:
            return ["CPUExecutionProvider"]

    def _init_separator(self, model_name: str):
        """Initialize the audio-separator with the specified model."""
        try:
            print(f"[{self.__class__.__name__}] Loading model: {model_name}")
            print(f"[{self.__class__.__name__}] (First run will download weights automatically)")

            # Patch for PyInstaller: importlib.metadata can't find dist-info
            # in frozen binaries, so get_package_distribution() returns None
            # and .version crashes with "'NoneType' has no attribute 'version'"
            _orig_get_dist = getattr(Separator, 'get_package_distribution', None)
            if _orig_get_dist:
                def _safe_get_dist(self_sep, package_name):
                    dist = _orig_get_dist(self_sep, package_name)
                    if dist is None:
                        class _FakeDist:
                            version = "0.0.0-frozen"
                        return _FakeDist()
                    return dist
                Separator.get_package_distribution = _safe_get_dist

            sep_kwargs = dict(
                log_level=logging.WARNING,
                model_file_dir=self.model_dir,
                output_dir=self.temp_dir,
            )
            # Inject CoreML ONNX providers if available
            if self._ort_providers and "CoreMLExecutionProvider" in self._ort_providers:
                sep_kwargs["onnx_execution_providers"] = self._ort_providers

            self.separator = Separator(**sep_kwargs)

            # audio-separator 0.41.1+: custom models (e.g. BS-RoFormer) are NOT in
            # the package's built-in registry. load_model_data_from_yaml() must be
            # called first to inject the model metadata before load_model().
            model_stem = os.path.splitext(model_name)[0]
            yaml_path = os.path.join(self.model_dir, f"{model_stem}.yaml")
            if os.path.exists(yaml_path) and hasattr(self.separator, 'load_model_data_from_yaml'):
                print(f"[{self.__class__.__name__}] Loading model config from YAML: {os.path.basename(yaml_path)}")
                self.separator.load_model_data_from_yaml(yaml_path)

            self.separator.load_model(model_filename=model_name)
            self.model_loaded = True
            print(f"[{self.__class__.__name__}] ✓ Model loaded: {model_name}")

        except Exception as e:
            print(f"[{self.__class__.__name__}] Model load failed ({model_name}): {e}")
            self.model_loaded = False

            # Try fallback model if primary failed
            if model_name == PRIMARY_MODEL:
                print(f"[{self.__class__.__name__}] Trying fallback model: {FALLBACK_MODEL}")
                self._init_separator(FALLBACK_MODEL)

    def process(self, input_audio_path: str) -> str:
        """
        Extract vocals from the input audio file.
        Returns path to the isolated vocals WAV.
        Falls back to returning input on failure.
        """
        if not self.model_loaded or not self.separator:
            print(f"[{self.__class__.__name__}] No model loaded — returning input unmodified.")
            return input_audio_path

        fname = os.path.basename(input_audio_path)
        print(f"[{self.__class__.__name__}] Separating vocals from: {fname}")

        # Validate input exists
        if not os.path.exists(input_audio_path):
            print(f"[{self.__class__.__name__}] Input file not found: {input_audio_path}")
            return input_audio_path

        try:
            # Run separation
            output_files = self.separator.separate(input_audio_path)

            # Find the vocals file in the output
            vocal_path = self._find_vocals(output_files)

            if vocal_path:
                # Validate output
                out_size = os.path.getsize(vocal_path)
                if out_size < 1024:  # Less than 1KB is suspicious
                    print(f"[{self.__class__.__name__}] ⚠ Output suspiciously small ({out_size}B)")
                    return input_audio_path

                print(f"[{self.__class__.__name__}] ✓ Vocals isolated: {os.path.basename(vocal_path)} "
                      f"({out_size / 1024 / 1024:.1f} MB)")
                return vocal_path
            else:
                print(f"[{self.__class__.__name__}] Could not locate vocals in output.")
                return input_audio_path

        except Exception as e:
            print(f"[{self.__class__.__name__}] Separation failed: {e}")
            return input_audio_path

        finally:
            # Free GPU memory after separation
            self._cleanup_memory()

    def _find_vocals(self, output_files: list) -> str | None:
        """
        Locate the vocals file from separator output.
        audio-separator returns filenames relative to output_dir.
        """
        vocal_keywords = ["vocal", "voice", "singing"]
        for f in output_files:
            f_lower = f.lower()
            if any(kw in f_lower for kw in vocal_keywords):
                full_path = os.path.join(self.temp_dir, f) if not os.path.isabs(f) else f
                if os.path.exists(full_path):
                    return full_path

        # If no keyword match, return the first output that exists
        for f in output_files:
            full_path = os.path.join(self.temp_dir, f) if not os.path.isabs(f) else f
            if os.path.exists(full_path):
                return full_path

        return None

    def _cleanup_memory(self):
        """Force garbage collection and clear GPU cache."""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
            torch.mps.empty_cache()
