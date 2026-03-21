import platform
import torch

class DeviceOptimizer:
    """
    Utility class for cross-platform model hardware acceleration in Trinity V8.1.
    Handles dynamic detection of CUDA (NVIDIA), MPS (Apple Silicon), and CPU.
    """
    
    @classmethod
    def get_optimal_device(cls) -> torch.device:
        """Returns the optimal torch.device available on the system."""
        if cls._force_cpu:
            return torch.device("cpu")
        if torch.cuda.is_available():
            return torch.device("cuda")
        elif torch.backends.mps.is_available():
            return torch.device("mps")
        else:
            return torch.device("cpu")

    @classmethod
    def get_device_string(cls) -> str:
        """Returns string representation 'cuda', 'mps', or 'cpu' for external libraries."""
        if cls._force_cpu:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"

    @staticmethod
    def is_cuda_available() -> bool:
        return torch.cuda.is_available()

    @staticmethod
    def is_mps_available() -> bool:
        return hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()

    @staticmethod
    def is_apple_silicon() -> bool:
        """True on Apple Silicon (M-series) macOS."""
        return platform.system() == "Darwin" and platform.machine() == "arm64"

    @staticmethod
    def is_coreml_available() -> bool:
        """True when coremltools is installed and running on Apple Silicon."""
        if not DeviceOptimizer.is_apple_silicon():
            return False
        try:
            import coremltools  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def is_directml_available() -> bool:
        """True when DirectML (DirectX 12 GPU) is available on Windows."""
        if platform.system() != "Windows":
            return False
        try:
            import onnxruntime as ort
            return "DmlExecutionProvider" in ort.get_available_providers()
        except ImportError:
            return False

    @staticmethod
    def is_onnx_available() -> bool:
        """True when ONNX Runtime is installed for cross-platform acceleration."""
        try:
            import onnxruntime  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def get_acceleration_summary() -> str:
        """Human-readable acceleration path for current hardware."""
        if DeviceOptimizer.is_coreml_available():
            return "CoreML (Neural Engine + GPU + CPU)"
        if DeviceOptimizer.is_directml_available():
            return "DirectML (DirectX 12 GPU)"
        if DeviceOptimizer.is_mps_available():
            return "MPS (Apple GPU)"
        if DeviceOptimizer.is_cuda_available():
            return "CUDA (NVIDIA GPU)"
        if DeviceOptimizer.is_onnx_available():
            return "ONNX Runtime (CPU optimized)"
        return "CPU"

    @staticmethod
    def move_to_optimal_device(tensor: torch.Tensor) -> torch.Tensor:
        """Moves a given tensor to the optimal compute device."""
        device = DeviceOptimizer.get_optimal_device()
        return tensor.to(device)

    @staticmethod
    def decoupled_stft(audio_tensor, n_fft=1024, hop_length=256, win_length=None):
        """
        Executes STFT strictly on the CPU.
        Apple Silicon MPS backend currently struggles with complex number operations in STFT.
        """
        cpu_tensor = audio_tensor.to(torch.device("cpu"))
        return torch.stft(
            cpu_tensor,
            n_fft=n_fft,
            hop_length=hop_length,
            win_length=win_length,
            return_complex=True
        )

    @staticmethod
    def decoupled_istft(stft_matrix, n_fft=1024, hop_length=256, win_length=None):
        """
        Executes iSTFT strictly on the CPU to reconstruct the audio waveform from a complex STFT matrix.
        """
        cpu_matrix = stft_matrix.to(torch.device("cpu"))
        return torch.istft(
            cpu_matrix,
            n_fft=n_fft,
            hop_length=hop_length,
            win_length=win_length
        )

    # ── Forced CPU Context Manager ──────────────────────────────────────

    _force_cpu = False

    @classmethod
    def force_cpu_context(cls):
        """
        Context manager that temporarily forces all device queries to return CPU.
        Used by the RetryEngine's cpu_retry fallback strategy.
        
        Usage:
            with DeviceOptimizer.force_cpu_context():
                model = load_model(device=DeviceOptimizer.get_device_string())
                # ^ will return 'cpu' regardless of GPU availability
        """
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            cls._force_cpu = True
            print("[DeviceOptimizer] ⚠ FORCED CPU MODE ACTIVE")
            try:
                yield
            finally:
                cls._force_cpu = False
                print("[DeviceOptimizer] Restored default device selection")

        return _ctx()

    # ── RAM Budget Guard ─────────────────────────────────────────────────

    _ram_limit_pct = 75  # Default 75% — set via CLI --ram-limit

    @classmethod
    def set_ram_limit(cls, pct: int):
        """Set the RAM usage ceiling as a percentage of total system RAM (25-100)."""
        cls._ram_limit_pct = max(25, min(100, pct))
        print(f"[DeviceOptimizer] RAM limit set to {cls._ram_limit_pct}%")

    @classmethod
    def check_ram_budget(cls) -> dict:
        """Check current RAM usage against the configured limit."""
        try:
            import psutil
            vm = psutil.virtual_memory()
            total_gb = vm.total / (1024**3)
            used_gb  = vm.used / (1024**3)
            avail_gb = vm.available / (1024**3)
            limit_gb = total_gb * (cls._ram_limit_pct / 100.0)
            usage_pct = round((used_gb / total_gb) * 100, 1)
            return {
                "total_gb":      round(total_gb, 2),
                "used_gb":       round(used_gb, 2),
                "available_gb":  round(avail_gb, 2),
                "limit_gb":      round(limit_gb, 2),
                "limit_pct":     cls._ram_limit_pct,
                "usage_pct":     usage_pct,
                "within_budget": used_gb <= limit_gb,
            }
        except ImportError:
            return {"within_budget": True, "usage_pct": 0, "limit_pct": cls._ram_limit_pct}

    @classmethod
    def enforce_ram_limit(cls, stage_name: str = "") -> bool:
        """
        Enforce the RAM limit before loading a model.
        If over budget, run GC + cache clear and re-check.
        Returns True if within budget (ok to proceed), False if still over.
        """
        budget = cls.check_ram_budget()
        if budget["within_budget"]:
            return True

        # Attempt cleanup
        import gc
        gc.collect()

        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
                torch.mps.empty_cache()
        except Exception:
            pass

        # Re-check after cleanup
        budget = cls.check_ram_budget()
        pct = budget.get("usage_pct", 0)
        limit = budget.get("limit_pct", 75)

        if not budget["within_budget"]:
            print(f"[RAM GUARD] WARNING {stage_name}: RAM at {pct}% exceeds {limit}% limit "
                  f"({budget.get('used_gb', '?')}GB / {budget.get('limit_gb', '?')}GB cap) — proceeding cautiously")
            return False

        print(f"[RAM GUARD] OK {stage_name}: RAM within budget after GC ({pct}%)")
        return True

    @staticmethod
    def cleanup_memory():
        """Release GPU/MPS cache and run Python GC. Call after each pipeline stage."""
        import gc
        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
                torch.mps.empty_cache()
        except Exception:
            pass

    @staticmethod
    def get_memory_info() -> dict:
        """
        Returns a dictionary with available memory diagnostics.
        Works on both macOS and Windows. Falls back gracefully if psutil is unavailable.
        """
        import platform
        info = {"platform": platform.system(), "arch": platform.machine()}

        try:
            import psutil
            info["system_ram_total_gb"] = round(psutil.virtual_memory().total / (1024**3), 2)
            info["system_ram_available_gb"] = round(psutil.virtual_memory().available / (1024**3), 2)
            info["system_ram_percent_used"] = psutil.virtual_memory().percent
        except ImportError:
            info["system_ram_total_gb"] = "unknown (psutil not installed)"

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                allocated = torch.cuda.memory_allocated(i) / (1024**3)
                reserved = torch.cuda.memory_reserved(i) / (1024**3)
                total = torch.cuda.get_device_properties(i).total_mem / (1024**3)
                info[f"gpu_{i}_allocated_gb"] = round(allocated, 2)
                info[f"gpu_{i}_reserved_gb"] = round(reserved, 2)
                info[f"gpu_{i}_total_gb"] = round(total, 2)

        return info

