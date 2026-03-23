import time
import functools
import traceback

class RetryEngine:
    """
    Decorator-based retry controller with exponential backoff and automatic fallback.
    Designed for ML pipeline stages that may fail due to GPU memory, driver issues, etc.
    """

    @staticmethod
    def resilient_stage(stage_name: str, retries: int = 3, fallback: str = "passthrough", telemetry=None):
        """
        Decorator that wraps a pipeline stage function with retry + fallback logic.
        
        Args:
            stage_name: Human-readable name for logging (e.g. "DeepFilterNet Denoise").
            retries:    Max retry attempts before falling back.
            fallback:   Strategy on total failure:
                        - "passthrough" → return the input audio unmodified.
                        - "cpu_retry"   → force CPU and retry once more.
            telemetry:  Optional ErrorTelemetryController instance for logging.
        """
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                last_exception = None

                for attempt in range(1, retries + 1):
                    try:
                        result = func(*args, **kwargs)
                        # Validate result — a stage must return a non-None string path
                        if result is None:
                            raise RuntimeError(f"{stage_name} returned None — no output produced")
                        return result
                    except Exception as e:
                        last_exception = e
                        backoff = 0.5 * (2 ** (attempt - 1))  # 0.5s, 1s, 2s
                        print(f"[RetryEngine] [!] {stage_name} failed (attempt {attempt}/{retries}): {e}")
                        traceback.print_exc()
                        
                        if telemetry:
                            telemetry.log_error(
                                stage=f"{stage_name} (attempt {attempt})",
                                exception=e,
                                metadata={"fallback": fallback, "attempt": attempt}
                            )
                        
                        if attempt < retries:
                            print(f"[RetryEngine] Retrying in {backoff}s...")
                            time.sleep(backoff)

                # All retries exhausted — execute fallback
                print(f"[RetryEngine] ✗ {stage_name} exhausted {retries} retries.")

                if fallback == "cpu_retry":
                    print(f"[RetryEngine] Attempting CPU fallback for {stage_name}...")
                    try:
                        from modules.device_utils import DeviceOptimizer
                        with DeviceOptimizer.force_cpu_context():
                            return func(*args, **kwargs)
                    except Exception as cpu_e:
                        print(f"[RetryEngine] CPU fallback also failed: {cpu_e}")
                        traceback.print_exc()
                        if telemetry:
                            telemetry.log_error(
                                stage=f"{stage_name} (CPU fallback)",
                                exception=cpu_e
                            )

                # Passthrough fallback — return input audio path
                # NOTE: For bound methods (self, input_wav, ...), args[0] is self,
                # args[1] is the actual input audio path.
                if fallback in ("passthrough", "cpu_retry"):
                    if len(args) >= 2:
                        input_path = args[1]  # Bound method: args = (self, input_wav, ...)
                    elif len(args) == 1:
                        input_path = args[0]  # Standalone function: args = (input_wav, ...)
                    else:
                        input_path = kwargs.get("input_wav", kwargs.get("input_audio_path", None))
                    print(f"[RetryEngine] ↩ PASSTHROUGH — returning input unmodified for {stage_name}")
                    return input_path

                # If somehow no fallback matched, raise the last exception
                raise last_exception

            return wrapper
        return decorator

