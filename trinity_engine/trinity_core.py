# VOXIS V4.0.0 DENSE — TRINITY V8.1 ENGINE (DESKTOP)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
# Timestamp: 2026-03-15
#
# Pipeline:
#   1. INGEST      — FFmpeg universal decode (audio + video)
#   2. SEPARATE    — Glass Stone Separator (BS-RoFormer)
#   3. ANALYZE     — Spectrum Noise Profile + Auto-EQ
#   4. DENOISE     — DeepFilterNet3 (Pre-Diffusion)
#   5. UPSCALE     — AudioSR latent diffusion 48kHz + post-diffusion denoise
#   6. MASTER      — Pedalboard Limiter + Stereo Width
#   7. EXPORT      — 24-bit WAV or FLAC
#
# Performance: Lazy model loading — models only load when their stage
#              is first called, reducing startup from ~170s to ~2s.

import os
import sys
import time
import platform
import argparse
import warnings

# Suppress noisy third-party deprecation warnings
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="chardet.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="charset_normalizer.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="`torchaudio.backend.common.AudioMetaData` has been moved")

# Enable MPS fallback for ops not supported on Apple Silicon (e.g. AudioSR channels)
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# ── Lightweight imports only (no ML frameworks at module level) ──────────────
from modules.ingest import AudioDecoder
from modules.error_telemetry import ErrorTelemetryController
from modules.pipeline_cache import PipelineCache
from modules.retry_engine import RetryEngine


class TrinityV8Desktop:
    """
    Trinity V8.1 pipeline with lazy model loading.
    __init__ completes in ~2s. ML models load on first use.
    """

    def __init__(self):
        t0 = time.perf_counter()
        print(">> [SYSTEM] INITIALIZING TRINITY V8.1 DESKTOP ENGINE...")
        print(f">> [SYSTEM] Platform: {platform.system()} {platform.machine()}")
        print(">> [SYSTEM] Copyright © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez")

        # ── Infrastructure (lightweight) ─────────────────────────────────
        self.telemetry = ErrorTelemetryController()
        self.cache     = PipelineCache()
        self.decoder   = AudioDecoder()

        # ── Lazy-loaded pipeline nodes (None until first use) ────────────
        self._separator = None
        self._profiler  = None
        self._denoiser  = None
        self._upscaler  = None
        self._limiter   = None

        init_time = time.perf_counter() - t0
        print(f">> [SYSTEM] Engine ready in {init_time:.2f}s (models load on demand)")

    # ── Lazy accessors ────────────────────────────────────────────────────

    @property
    def separator(self):
        if self._separator is None:
            from modules.uvr_processor import GlassStoneSeparator
            self._separator = GlassStoneSeparator()
        return self._separator

    @property
    def profiler(self):
        if self._profiler is None:
            from modules.spectrum_analyzer import NoiseProfiler
            self._profiler = NoiseProfiler()
        return self._profiler

    @property
    def denoiser(self):
        if self._denoiser is None:
            from modules.voicerestore_wrapper import VoiceRestoreWrapper
            self._denoiser = VoiceRestoreWrapper()
        return self._denoiser

    @property
    def upscaler(self):
        if self._upscaler is None:
            from modules.upsampler import TrinityUpscaler
            self._upscaler = TrinityUpscaler()
        return self._upscaler

    @property
    def limiter(self):
        if self._limiter is None:
            from modules.mastering_phase import PedalboardMastering
            self._limiter = PedalboardMastering()
        return self._limiter

    # ── Retry-wrapped stage methods ─────────────────────────────────────

    @RetryEngine.resilient_stage("SEPARATE (BS-RoFormer)", retries=2, fallback="passthrough")
    def _stage_separate(self, input_wav):
        return self.separator.process(input_wav)

    @RetryEngine.resilient_stage("DENOISE (DeepFilterNet3)", retries=3, fallback="cpu_retry")
    def _stage_denoise(self, input_wav, stage="pre-diffusion"):
        return self.denoiser.process(input_wav, stage=stage)

    @RetryEngine.resilient_stage("UPSCALE (AudioSR)", retries=2, fallback="passthrough")
    def _stage_upscale(self, input_wav, target_sr=48000):
        return self.upscaler.super_resolve(input_wav, target_sr=target_sr)

    @RetryEngine.resilient_stage("MASTER (Pedalboard)", retries=2, fallback="passthrough")
    def _stage_master(self, input_wav, width=0.50, lowpass_hz=20000.0, highpass_hz=20.0, vocal_presence_db=0.0):
        return self.limiter.apply(input_wav, width=width,
                                 lowpass_hz=lowpass_hz, highpass_hz=highpass_hz,
                                 vocal_presence_db=vocal_presence_db)

    # ── Main Pipeline ───────────────────────────────────────────────────

    def run_pipeline(self, input_path: str, output_path: str, params: dict) -> bool:
        """
        Execute the full Voxis V4.0.0 DENSE restoration pipeline.
        Models load lazily on first pipeline run (~30-60s first time, <1s after).
        """
        fname = os.path.basename(input_path)
        pipeline_start = time.perf_counter()

        # ── Input validation ───────────────────────────────────────────
        if not os.path.exists(input_path):
            print(f"\n[CRITICAL ERROR] Input file not found: {input_path}")
            return False

        print(f"\n{'='*60}")
        print(f"  VOXIS V4.0.0 DENSE :: Processing '{fname}'")
        print(f"  Mode: {params.get('denoise_mode', 'HIGH')} | "
              f"Width: {float(params.get('stereo_width', 0.50)) * 100:.0f}% | "
              f"Format: {params.get('output_format', 'WAV')}")
        print(f"{'='*60}\n")

        # Generate cache key from file content + params
        job_key = self.cache.make_job_key(input_path, params)
        print(f">> [CACHE] Job Key: {job_key}")

        try:
            # ── Device info (lazy — imports torch only now) ─────────────
            try:
                from modules.device_utils import DeviceOptimizer
                mem = DeviceOptimizer.get_memory_info()
                print(f">> [SYSTEM] Device: {DeviceOptimizer.get_device_string().upper()} | "
                      f"RAM: {mem.get('system_ram_available_gb', '?')}GB free / "
                      f"{mem.get('system_ram_total_gb', '?')}GB total")
            except Exception:
                pass

            # ── STEP 1/6 · INGEST ───────────────────────────────────────
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "01_ingest")
            if cached:
                working_wav = cached
            else:
                print(">> [1/6] Executing FFMPEG Decoder Extraction...")
                working_wav = self.decoder.decode_to_wav(input_path)
                self.cache.put(job_key, "01_ingest", working_wav)
            print(f"   ⏱ Ingest: {time.perf_counter() - t0:.2f}s")

            # ── STEP 2/6 · SEPARATE ─────────────────────────────────────
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "02_separate")
            if cached:
                vocal_wav = cached
            else:
                print(">> [2/6] Executing Glass Stone Separator (BS-RoFormer)...")
                vocal_wav = self._stage_separate(working_wav)
                self.cache.put(job_key, "02_separate", vocal_wav)
            print(f"   ⏱ Separate: {time.perf_counter() - t0:.2f}s")

            # ── STEP 3/6 · ANALYZE ──────────────────────────────────────
            t0 = time.perf_counter()
            print(">> [3/6] Spectrum Analysis & Noise Profiling...")
            from modules.spectrum_analyzer import NoiseProfiler
            noise_profile = self.profiler.analyze(vocal_wav)

            # ── AUTO-EQ: derive optimal filter settings from spectral profile ──
            try:
                auto_eq = NoiseProfiler.compute_auto_eq(noise_profile)
            except Exception as eq_err:
                print(f"[WARNING] Auto-EQ computation failed: {eq_err}")
                auto_eq = {'lowpass_hz': 20000.0, 'highpass_hz': 20.0, 'vocal_presence_db': 0.0}

            # Emit structured auto-EQ line so the UI can parse and display it
            print(
                f"[NoiseProfiler] Auto-EQ: "
                f"HPF={int(auto_eq.get('highpass_hz', 20))}Hz | "
                f"LPF={int(auto_eq.get('lowpass_hz', 20000))}Hz | "
                f"Vocal={auto_eq.get('vocal_presence_db', 0.0):+.1f}dB"
            )
            print(f"   ⏱ Analyze: {time.perf_counter() - t0:.2f}s")

            # ── STEP 4/6 · DENOISE ──────────────────────────────────────
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "04_denoise")
            if cached:
                enhanced_wav_1 = cached
            else:
                print(">> [4/6] Neural Denoise Inference (DeepFilterNet3)...")
                enhanced_wav_1 = self._stage_denoise(vocal_wav, stage="pre-diffusion")
                self.cache.put(job_key, "04_denoise", enhanced_wav_1)
            print(f"   ⏱ Denoise: {time.perf_counter() - t0:.2f}s")

            # ── STEP 5/6 · UPSCALE (post-diffusion denoise → then resample) ─
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "05_upscale")
            if cached:
                enhanced_wav_2 = cached
            else:
                print(">> [5/6] Trinity AudioSR Diffusion Upscale to 48kHz...")
                # Post-diffusion cleanup FIRST (VoiceRestore outputs 24kHz),
                # then upscale so the final sample rate sticks at 48kHz.
                post_denoised = self._stage_denoise(enhanced_wav_1, stage="post-diffusion")
                enhanced_wav_2 = self._stage_upscale(post_denoised, target_sr=48000)
                self.cache.put(job_key, "05_upscale", enhanced_wav_2)
            print(f"   ⏱ Upscale: {time.perf_counter() - t0:.2f}s")

            # ── STEP 6/6 · MASTER ───────────────────────────────────────
            t0 = time.perf_counter()
            width = float(params['stereo_width'])
            cached = self.cache.get(job_key, "06_master")
            if cached:
                mastered_wav = cached
            else:
                print(f">> [6/6] Pedalboard AI Mastering & Auto-EQ...")
                mastered_wav = self._stage_master(
                    enhanced_wav_2,
                    width=width,
                    lowpass_hz=auto_eq.get('lowpass_hz', 20000.0),
                    highpass_hz=auto_eq.get('highpass_hz', 20.0),
                    vocal_presence_db=auto_eq.get('vocal_presence_db', 0.0),
                )
                self.cache.put(job_key, "06_master", mastered_wav)
            print(f"   ⏱ Master: {time.perf_counter() - t0:.2f}s")

            # ── EXPORT ──────────────────────────────────────────────────
            t0 = time.perf_counter()
            print(">> Finalizing Export — multiplexing output...")
            self.decoder.finalize_export(mastered_wav, input_path, output_path,
                                         fmt=params.get('output_format', 'WAV'))
            print(f"   ⏱ Export: {time.perf_counter() - t0:.2f}s")

            total = time.perf_counter() - pipeline_start
            print(f"\n{'='*60}")
            print(f"  ✓ Restoration Complete → {os.path.basename(output_path)}")
            print(f"  Total Pipeline Time: {total:.2f}s")
            print(f"{'='*60}\n")
            return True

        except Exception as e:
            print(f"\n[CRITICAL ERROR] Pipeline Failed: {e}")
            self.telemetry.log_error(
                stage="Pipeline Execution",
                exception=e,
                metadata={"input_file": fname, "platform": platform.system()}
            )
            return False

    def cleanup(self):
        """Purges the trinity_temp working directory after a successful run."""
        import shutil
        base_dir = os.path.dirname(os.path.abspath(__file__))
        temp_dir = os.path.join(base_dir, "trinity_temp")
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("[Cleanup] Purged trinity_temp working directory.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VOXIS V4.0.0 DENSE — Trinity V8.1 Backend | Glass Stone LLC © 2026"
    )
    parser.add_argument("--input",        required=True,  help="Input audio/video file path")
    parser.add_argument("--output",       required=True,  help="Output file path")
    parser.add_argument("--extreme",      action="store_true", help="Use EXTREME denoise mode")
    parser.add_argument("--stereo-width", type=float, default=0.50,
                        help="Stereo width 0.0–1.0 (default 0.50)")
    parser.add_argument("--format",       default="WAV", choices=["WAV", "FLAC"],
                        help="Output format: WAV (default) or FLAC")
    args = parser.parse_args()

    engine = TrinityV8Desktop()
    success = engine.run_pipeline(
        input_path=args.input,
        output_path=args.output,
        params={
            "denoise_mode":  "EXTREME" if args.extreme else "HIGH",
            "stereo_width":  args.stereo_width,
            "output_format": args.format,
        }
    )

    if success:
        engine.cleanup()

    sys.exit(0 if success else 1)
