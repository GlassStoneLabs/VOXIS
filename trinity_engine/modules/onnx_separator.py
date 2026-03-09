# VOXIS V4.0.0 DENSE — ONNX Separator Module
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
#
# High-performance source separation using ONNX Runtime.
# Supports CUDA, DirectML (Windows), CoreML (macOS), and CPU.
# Falls back gracefully if ONNX models are not available.

import os
import sys
import subprocess
import shutil
import numpy as np
from .device_utils import DeviceOptimizer
from .path_utils import get_engine_base_dir

# Try to import ONNX runtime
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

# Try to import soundfile for I/O
try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False


def _get_onnx_providers():
    """
    Returns the best ONNX Runtime execution providers for the current platform.
    Priority: CUDA > CoreML > DirectML > CPU.
    """
    device = DeviceOptimizer.get_device_string()
    providers = []

    if device == "cuda" and "CUDAExecutionProvider" in ort.get_available_providers():
        providers.append("CUDAExecutionProvider")
    elif sys.platform == "darwin" and "CoreMLExecutionProvider" in ort.get_available_providers():
        providers.append("CoreMLExecutionProvider")
    elif sys.platform == "win32" and "DmlExecutionProvider" in ort.get_available_providers():
        providers.append("DmlExecutionProvider")

    providers.append("CPUExecutionProvider")  # Always as fallback
    return providers


class OnnxSeparatorWrapper:
    """
    Source separation using ONNX Runtime with BS-RoFormer or UVR models.
    Handles model loading, I/O, and cross-platform provider selection.
    """

    MODEL_FILENAME = "vocals_bs_roformer.onnx"

    def __init__(self):
        self.device = DeviceOptimizer.get_device_string()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.model_dir = os.path.join(base_dir, "dependencies", "models", "onnx_separator")
        self.temp_dir = os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        self.session = None
        self.model_path = os.path.join(self.model_dir, self.MODEL_FILENAME)

        print(f"[{self.__class__.__name__}] Device: {self.device}")
        print(f"[{self.__class__.__name__}] ONNX Runtime: {'available' if ONNX_AVAILABLE else 'NOT FOUND'}")
        print(f"[{self.__class__.__name__}] Model path: {self.model_path}")

        if ONNX_AVAILABLE and os.path.isfile(self.model_path):
            self._load_model()
        elif ONNX_AVAILABLE:
            print(f"[{self.__class__.__name__}] ONNX model not found at {self.model_path}. "
                  f"Will fall back to audio-separator (PyTorch).")
        else:
            print(f"[{self.__class__.__name__}] onnxruntime not installed. "
                  f"Install with: pip install onnxruntime")

    def _load_model(self):
        """Load the ONNX model with optimal providers."""
        try:
            providers = _get_onnx_providers()
            print(f"[{self.__class__.__name__}] Loading ONNX model with providers: {providers}")

            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = os.cpu_count() or 4
            sess_options.inter_op_num_threads = 2

            self.session = ort.InferenceSession(
                self.model_path,
                sess_options=sess_options,
                providers=providers,
            )
            active = self.session.get_providers()
            print(f"[{self.__class__.__name__}] ✓ ONNX session active — providers: {active}")
        except Exception as e:
            print(f"[{self.__class__.__name__}] ONNX session init failed: {e}")
            self.session = None

    def process(self, input_audio_path: str) -> str:
        """
        Run separation inference on the input audio.
        Returns the path to the isolated vocals WAV.
        Falls back to returning the input if model unavailable.
        """
        print(f"[{self.__class__.__name__}] Processing: {os.path.basename(input_audio_path)}")

        # If ONNX session is loaded, use it
        if self.session and SOUNDFILE_AVAILABLE:
            return self._onnx_inference(input_audio_path)

        # Fallback: try the audio-separator PyTorch backend
        return self._fallback_separator(input_audio_path)

    def _onnx_inference(self, input_audio_path: str) -> str:
        """Run actual ONNX inference."""
        try:
            audio, sr = sf.read(input_audio_path, dtype="float32")
            if audio.ndim == 1:
                audio = np.stack([audio, audio], axis=-1)  # Mono → stereo

            # Prepare input tensor: (1, channels, samples)
            audio_t = np.transpose(audio).astype(np.float32)
            audio_t = np.expand_dims(audio_t, axis=0)

            # Get input/output names
            input_name = self.session.get_inputs()[0].name
            output_name = self.session.get_outputs()[0].name

            # Run inference
            print(f"[{self.__class__.__name__}] ONNX inference running...")
            result = self.session.run([output_name], {input_name: audio_t})

            # Extract vocals
            vocals = result[0].squeeze()
            if vocals.ndim == 1:
                vocals = np.stack([vocals, vocals], axis=-1)
            elif vocals.ndim == 2 and vocals.shape[0] == 2:
                vocals = np.transpose(vocals)

            # Save output
            base_name = os.path.splitext(os.path.basename(input_audio_path))[0]
            out_path = os.path.join(self.temp_dir, f"{base_name}_vocals_onnx.wav")
            sf.write(out_path, vocals, sr, subtype="PCM_16")

            print(f"[{self.__class__.__name__}] ✓ ONNX separation complete → {os.path.basename(out_path)}")
            return out_path

        except Exception as e:
            print(f"[{self.__class__.__name__}] ONNX inference failed: {e}")
            return self._fallback_separator(input_audio_path)

    def _fallback_separator(self, input_audio_path: str) -> str:
        """
        Fallback to the audio-separator PyTorch backend (GlassStoneSeparator).
        This is imported lazily to avoid circular deps.
        """
        try:
            from .uvr_processor import GlassStoneSeparator
            print(f"[{self.__class__.__name__}] Falling back to PyTorch BS-RoFormer (audio-separator)...")
            sep = GlassStoneSeparator()
            return sep.process(input_audio_path)
        except Exception as e:
            print(f"[{self.__class__.__name__}] Fallback also failed: {e}. Returning input.")
            return input_audio_path
