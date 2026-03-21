# VOXIS V4.0.0 DENSE — TRINITY V8.1 ENGINE (DESKTOP)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
# Timestamp: 2026-03-15
#
# Pipeline:
#   1. INGEST      — FFmpeg universal decode (audio + video)
#   2. SEPARATE    — GS-PRISM Voice Isolation
#   3. ANALYZE     — Spectrum Noise Profile + Auto-EQ
#   4. DENOISE     — GS-CRYSTAL Neural Restoration (Pre-Diffusion)
#   5. UPSCALE     — GS-ASCEND Latent Diffusion 48kHz + post-diffusion denoise
#   6. MASTER      — Pedalboard Limiter + Stereo Width
#   7. EXPORT      — 24-bit WAV or FLAC
#
# Performance: Lazy model loading — models only load when their stage
#              is first called, reducing startup from ~170s to ~2s.

import os
import sys
import gc
import time
import platform
import argparse
import warnings

# Suppress noisy third-party deprecation warnings
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="chardet.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="charset_normalizer.*doesn't match a supported version")
warnings.filterwarnings("ignore", message="`torchaudio.backend.common.AudioMetaData` has been moved")
# torch FutureWarnings from rotary_embedding_torch and weight_norm
warnings.filterwarnings("ignore", category=FutureWarning, message=".*torch.cuda.amp.autocast.*")
warnings.filterwarnings("ignore", category=FutureWarning, message=".*torch.amp.autocast.*")
warnings.filterwarnings("ignore", category=FutureWarning, message=".*torch.nn.utils.weight_norm.*")

# Enable MPS fallback for ops not supported on Apple Silicon (e.g. AudioSR channels)
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# ── Lightweight imports only (no ML frameworks at module level) ──────────────
from modules.ingest import AudioDecoder
from modules.error_telemetry import ErrorTelemetryController
from modules.pipeline_cache import cache as pipeline_cache
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
        self.cache     = pipeline_cache
        self.decoder   = AudioDecoder()

        # ── Lazy-loaded pipeline nodes (None until first use) ────────────
        self._separator        = None
        self._profiler         = None
        self._denoiser         = None
        self._upscaler         = None
        self._limiter          = None
        self._mode             = "HIGH"
        self._denoise_steps    = 32
        self._denoise_strength = 0.65

        init_time = time.perf_counter() - t0
        print(f">> [SYSTEM] Engine ready in {init_time:.2f}s (models load on demand)")

    # ── Lazy accessors ────────────────────────────────────────────────────

    @property
    def separator(self):
        if self._separator is None:
            from modules.device_utils import DeviceOptimizer
            DeviceOptimizer.enforce_ram_limit("SEPARATE (GS-PRISM)")
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
            from modules.device_utils import DeviceOptimizer
            DeviceOptimizer.enforce_ram_limit("DENOISE (GS-CRYSTAL)")
            from modules.voicerestore_wrapper import VoiceRestoreWrapper
            self._denoiser = VoiceRestoreWrapper(
                mode=self._mode,
                steps_override=self._denoise_steps,
                cfg_override=self._denoise_strength,
            )
        return self._denoiser

    @property
    def upscaler(self):
        if self._upscaler is None:
            from modules.device_utils import DeviceOptimizer
            DeviceOptimizer.enforce_ram_limit("UPSCALE (GS-ASCEND)")
            from modules.upsampler import TrinityUpscaler
            self._upscaler = TrinityUpscaler(quality=self._mode)
        return self._upscaler

    @property
    def limiter(self):
        if self._limiter is None:
            from modules.mastering_phase import PedalboardMastering
            self._limiter = PedalboardMastering()
        return self._limiter

    # ── Retry-wrapped stage methods ─────────────────────────────────────

    @RetryEngine.resilient_stage("SEPARATE (GS-PRISM)", retries=2, fallback="passthrough")
    def _stage_separate(self, input_wav):
        return self.separator.process(input_wav)

    @RetryEngine.resilient_stage("DENOISE (GS-CRYSTAL)", retries=3, fallback="cpu_retry")
    def _stage_denoise(self, input_wav, stage="pre-diffusion"):
        return self.denoiser.process(input_wav, stage=stage)

    @RetryEngine.resilient_stage("UPSCALE (GS-ASCEND)", retries=2, fallback="passthrough")
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

        # Apply params — invalidate denoiser/upscaler if settings changed
        mode     = params.get('denoise_mode', 'HIGH')
        steps    = int(params.get('denoise_steps', 16))
        strength = float(params.get('denoise_strength', 0.55))
        if mode != self._mode or steps != self._denoise_steps or strength != self._denoise_strength:
            self._mode             = mode
            self._denoise_steps    = steps
            self._denoise_strength = strength
            self._denoiser = None
            self._upscaler = None

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
            # Import buffer: stat-based key (zero file I/O) checked first.
            # Avoids reading the file at all on repeat imports of the same source.
            t0 = time.perf_counter()
            ingest_key = self.cache.make_ingest_key(input_path)
            working_wav = self.cache.get(ingest_key, "01_ingest")
            if working_wav:
                print(">> [1/6] Import buffer hit — skipping FFmpeg decode.")
            else:
                cached = self.cache.get(job_key, "01_ingest")
                if cached:
                    working_wav = cached
                else:
                    print(">> [1/6] Executing FFMPEG Decoder Extraction...")
                    working_wav = self.decoder.decode_to_wav(input_path)
                    self.cache.put(job_key, "01_ingest", working_wav)
                self.cache.put(ingest_key, "01_ingest", working_wav)
            print(f"   ⏱ Ingest: {time.perf_counter() - t0:.2f}s")

            # ── STEP 2/6 · SEPARATE ─────────────────────────────────────
            gc.collect()  # Free ingest buffers before loading separator model
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "02_separate")
            if cached:
                vocal_wav = cached
            else:
                print(">> [2/6] Executing GS-PRISM Voice Isolation...")
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
            gc.collect()  # Free analyzer tensors before denoise model
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "04_denoise")
            if cached:
                enhanced_wav_1 = cached
            else:
                print(">> [4/6] GS-CRYSTAL Neural Restoration (Pre-Diffusion)...")
                enhanced_wav_1 = self._stage_denoise(vocal_wav, stage="pre-diffusion")
                self.cache.put(job_key, "04_denoise", enhanced_wav_1)
            print(f"   ⏱ Denoise: {time.perf_counter() - t0:.2f}s")

            # ── STEP 5/6 · UPSCALE (post-diffusion denoise → then resample) ─
            gc.collect()  # Free denoise model tensors before upscaler
            t0 = time.perf_counter()
            cached = self.cache.get(job_key, "05_upscale")
            if cached:
                enhanced_wav_2 = cached
            else:
                print(">> [5/6] GS-ASCEND Latent Diffusion Upscale to 48kHz...")
                # Post-diffusion cleanup FIRST (VoiceRestore outputs 24kHz),
                # then upscale so the final sample rate sticks at 48kHz.
                post_denoised = self._stage_denoise(enhanced_wav_1, stage="post-diffusion")
                enhanced_wav_2 = self._stage_upscale(post_denoised, target_sr=48000)
                self.cache.put(job_key, "05_upscale", enhanced_wav_2)
            print(f"   ⏱ Upscale: {time.perf_counter() - t0:.2f}s")

            # ── STEP 6/6 · MASTER ───────────────────────────────────────
            gc.collect()  # Free upscaler resources before mastering
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
        from modules.path_utils import get_engine_base_dir
        temp_dir = os.path.join(get_engine_base_dir(), "trinity_temp")
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("[Cleanup] Purged trinity_temp working directory.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="VOXIS V4.0.0 DENSE — Trinity V8.1 Backend | Glass Stone LLC © 2026"
    )
    parser.add_argument("--input",        required=True,  help="Input audio/video file path")
    parser.add_argument("--output",       required=True,  help="Output file path")
    parser.add_argument("--extreme",           action="store_true", help="Use EXTREME denoise mode")
    parser.add_argument("--stereo-width",      type=float, default=0.50,
                        help="Stereo width 0.0–1.0 (default 0.50)")
    parser.add_argument("--format",            default="WAV", choices=["WAV", "FLAC", "MP3"],
                        help="Output format: WAV (default), FLAC, or MP3")
    parser.add_argument("--ram-limit",         type=int, default=75,
                        help="RAM usage ceiling as percent of total system RAM (25-100, default 75)")
    parser.add_argument("--denoise-steps",     type=int, default=32,
                        help="GS-CRYSTAL diffusion steps (8–64, default 32)")
    parser.add_argument("--denoise-strength",  type=float, default=0.65,
                        help="GS-CRYSTAL CFG strength 0.1–1.0 (default 0.65)")
    args = parser.parse_args()

    # Apply RAM limit globally before any model loading
    from modules.device_utils import DeviceOptimizer
    DeviceOptimizer.set_ram_limit(args.ram_limit)
    print(f">> [SYSTEM] Acceleration: {DeviceOptimizer.get_acceleration_summary()}")

    engine = TrinityV8Desktop()
    success = engine.run_pipeline(
        input_path=args.input,
        output_path=args.output,
        params={
            "denoise_mode":     "EXTREME" if args.extreme else "HIGH",
            "stereo_width":     args.stereo_width,
            "output_format":    args.format,
            "denoise_steps":    args.denoise_steps,
            "denoise_strength": args.denoise_strength,
        }
    )

    if success:
        engine.cleanup()

    sys.exit(0 if success else 1)
