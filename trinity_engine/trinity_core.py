# VOXIS V4.0.0 DENSE — TRINITY V8.2 ENGINE (DESKTOP)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
# Timestamp: 2026-03-15
#
# Pipeline:
#   1. INGEST      — FFmpeg universal decode (audio + video)
#   2. SEPARATE    — GS-PRISM Voice Isolation (BS-RoFormer Transformer)
#   3. REFINE      — GS-REFINE Diff-HierVC Diffusion Refinement
#   4. ANALYZE     — Spectrum Noise Profile + Auto-EQ
#   5. DENOISE     — GS-CRYSTAL Neural Restoration (Pre-Diffusion)
#   6. UPSCALE     — GS-ASCEND Latent Diffusion 48kHz + post-diffusion denoise
#   7. MASTER      — Pedalboard Limiter + Stereo Width
#   8. EXPORT      — 24-bit WAV or FLAC
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
# coremltools / scikit-learn version mismatch (harmless — conversion API unused for sklearn)
warnings.filterwarnings("ignore", message=".*scikit-learn version.*is not supported.*")
warnings.filterwarnings("ignore", message=".*TracerWarning.*")

# Enable MPS fallback for ops not supported on Apple Silicon (e.g. AudioSR channels)
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# ── Lightweight imports only (no ML frameworks at module level) ──────────────
from modules.ingest import AudioDecoder
from modules.error_telemetry import ErrorTelemetryController
from modules.pipeline_cache import cache as pipeline_cache
from modules.retry_engine import RetryEngine
from modules.adaptive_chunker import AdaptiveChunker
from modules.temp_manager import TempFileManager

_DEFAULT_AUTO_EQ = {'lowpass_hz': 20000.0, 'highpass_hz': 20.0, 'vocal_presence_db': 0.0}


class TrinityV8Desktop:
    """
    Trinity V8.2 pipeline with lazy model loading.
    __init__ completes in ~2s. ML models load on first use.
    """

    def __init__(self):
        t0 = time.perf_counter()
        print(">> [SYSTEM] INITIALIZING TRINITY V8.2 DESKTOP ENGINE...")
        print(f">> [SYSTEM] Platform: {platform.system()} {platform.machine()}")
        print(">> [SYSTEM] Copyright © 2026 Glass Stone LLC — CEO: Gabriel B. Rodriguez")

        # ── Infrastructure (lightweight) ─────────────────────────────────
        self.telemetry = ErrorTelemetryController()
        self.cache     = pipeline_cache
        self.decoder   = None  # Created per-run with TempFileManager
        self._temp_manager = None  # Created per run_pipeline() call

        # ── Lazy-loaded pipeline nodes (None until first use) ────────────
        self._separator        = None
        self._refiner          = None
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
            self._separator = GlassStoneSeparator(temp_manager=self._temp_manager)
        return self._separator

    @property
    def refiner(self):
        if self._refiner is None:
            from modules.device_utils import DeviceOptimizer
            DeviceOptimizer.enforce_ram_limit("REFINE (GS-REFINE)")
            from modules.diffhiervc_wrapper import DiffHierVCWrapper
            self._refiner = DiffHierVCWrapper(temp_manager=self._temp_manager)
        return self._refiner

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
                temp_manager=self._temp_manager,
            )
        return self._denoiser

    @property
    def upscaler(self):
        if self._upscaler is None:
            from modules.device_utils import DeviceOptimizer
            DeviceOptimizer.enforce_ram_limit("UPSCALE (GS-ASCEND)")
            from modules.upsampler import TrinityUpscaler
            self._upscaler = TrinityUpscaler(quality=self._mode, temp_manager=self._temp_manager)
        return self._upscaler

    @property
    def limiter(self):
        if self._limiter is None:
            from modules.mastering_phase import PedalboardMastering
            self._limiter = PedalboardMastering(temp_manager=self._temp_manager)
        return self._limiter

    # ── Memory Optimization ──────────────────────────────────────────────

    def _free_model(self, attr_name: str, stage_name: str = ""):
        """Explicitly unloads a model and clears GPU/MPS/CPU cache to reclaim RAM."""
        if getattr(self, attr_name, None) is not None:
            setattr(self, attr_name, None)
            from modules.device_utils import DeviceOptimizer
            DeviceOptimizer.cleanup_memory()
            if stage_name:
                print(f">> [SYSTEM] Freed memory for {stage_name}")

    # ── Cache helper ─────────────────────────────────────────────────────

    def _cached_stage(self, cache_key: str, stage_id: str, fn, msg: str):
        """
        Check cache before running a stage. On miss: gc, log, run fn(), store result.
        Eliminates the repeated get/gc/print/put boilerplate across all stages.
        """
        result = self.cache.get(cache_key, stage_id)
        if not result:
            gc.collect()
            print(msg)
            result = fn()
            self.cache.put(cache_key, stage_id, result)
        return result

    # ── Horizontal Chunk Pipeline ────────────────────────────────────────

    def _process_chunks_horizontally(self, chunk_paths, params, job_key, num):
        """
        Run pipeline stages horizontally across all chunks to minimize RAM.
        Instead of running all stages per chunk, runs one stage for all chunks,
        then unloads the heavy AI model before loading the next.
        """
        current_paths = chunk_paths.copy()
        
        # ── 2/7 SEPARATE ──
        print(f"\n>> [CHUNKER] ── Stage 2: Separate ───────────────────────")
        for ci in range(num):
            c_path = current_paths[ci]
            chunk_key = self.cache.make_chunk_key(job_key, ci)
            tag = f"[{ci+1}/{num}]"
            current_paths[ci] = self._cached_stage(
                chunk_key, "02_separate",
                lambda p=c_path: self._stage_separate(p),
                f">> {tag} [2/7] GS-PRISM Voice Isolation (BS-RoFormer)...",
            )
        self._free_model('_separator', 'Separate')

        # ── 3/7 REFINE ──
        print(f"\n>> [CHUNKER] ── Stage 3: Refine ─────────────────────────")
        for ci in range(num):
            c_path = current_paths[ci]
            chunk_key = self.cache.make_chunk_key(job_key, ci)
            tag = f"[{ci+1}/{num}]"
            current_paths[ci] = self._cached_stage(
                chunk_key, "03_refine",
                lambda p=c_path: self._stage_refine(p),
                f">> {tag} [3/7] GS-REFINE Diffusion Refinement (Diff-HierVC)...",
            )
        self._free_model('_refiner', 'Refine')

        # ── 4/7 ANALYZE ──
        print(f"\n>> [CHUNKER] ── Stage 4: Analyze ────────────────────────")
        auto_eqs = [None] * num
        for ci in range(num):
            c_path = current_paths[ci]
            tag = f"[{ci+1}/{num}]"
            print(f">> {tag} [4/7] Spectrum Analysis...")
            noise_profile = self.profiler.analyze(c_path)
            try:
                auto_eqs[ci] = type(self.profiler).compute_auto_eq(noise_profile)
            except Exception:
                auto_eqs[ci] = _DEFAULT_AUTO_EQ

        # ── 5/7 DENOISE (Pre-Diffusion) ──
        print(f"\n>> [CHUNKER] ── Stage 5: Denoise (Pre) ──────────────────")
        for ci in range(num):
            c_path = current_paths[ci]
            chunk_key = self.cache.make_chunk_key(job_key, ci)
            tag = f"[{ci+1}/{num}]"
            current_paths[ci] = self._cached_stage(
                chunk_key, "05_denoise",
                lambda p=c_path: self._stage_denoise(p, stage="pre-diffusion"),
                f">> {tag} [5/7] GS-CRYSTAL Pre-Diffusion (VoiceRestore)...",
            )

        # ── Post-Diffusion Denoise ──
        print(f"\n>> [CHUNKER] ── Stage 5: Denoise (Post) ─────────────────")
        post_diffusion_paths = [None] * num
        for ci in range(num):
            c_path = current_paths[ci]
            chunk_key = self.cache.make_chunk_key(job_key, ci)
            tag = f"[{ci+1}/{num}]"
            post_diffusion_paths[ci] = self._cached_stage(
                chunk_key, "05_denoise_post",
                lambda p=c_path: self._stage_denoise(p, stage="post-diffusion"),
                f">> {tag} [5/7] GS-CRYSTAL Post-Diffusion Cleanup...",
            )
        self._free_model('_denoiser', 'Denoise')

        # ── 6/7 UPSCALE ──
        print(f"\n>> [CHUNKER] ── Stage 6: Upscale ────────────────────────")
        upscaled_paths = [None] * num
        for ci in range(num):
            c_path = post_diffusion_paths[ci]
            chunk_key = self.cache.make_chunk_key(job_key, ci)
            tag = f"[{ci+1}/{num}]"
            upscaled_paths[ci] = self._cached_stage(
                chunk_key, "06_upscale",
                lambda p=c_path: self._stage_upscale(p, target_sr=48000),
                f">> {tag} [6/7] GS-ASCEND Upscale (AudioSR)...",
            )
        self._free_model('_upscaler', 'Upscale')

        # ── 7/7 MASTER ──
        print(f"\n>> [CHUNKER] ── Stage 7: Master ─────────────────────────")
        width = float(params.get('stereo_width', 0.50))
        mastered_paths = [None] * num
        for ci in range(num):
            c_path = upscaled_paths[ci]
            auto_eq = auto_eqs[ci]
            chunk_key = self.cache.make_chunk_key(job_key, ci)
            tag = f"[{ci+1}/{num}]"
            mastered_paths[ci] = self._cached_stage(
                chunk_key, "07_master",
                lambda p=c_path, a=auto_eq: self._stage_master(
                    p,
                    width=width,
                    lowpass_hz=a.get('lowpass_hz', 20000.0),
                    highpass_hz=a.get('highpass_hz', 20.0),
                    vocal_presence_db=a.get('vocal_presence_db', 0.0),
                ),
                f">> {tag} [7/7] Mastering & Auto-EQ...",
            )
            print(f">> {tag} ✓ Chunk complete → {os.path.basename(mastered_paths[ci])}")
        self._free_model('_limiter', 'Master')

        return mastered_paths

    # ── Retry-wrapped stage methods ─────────────────────────────────────

    @RetryEngine.resilient_stage("SEPARATE (GS-PRISM)", retries=2, fallback="passthrough")
    def _stage_separate(self, input_wav):
        return self.separator.process(input_wav)

    @RetryEngine.resilient_stage("REFINE (GS-REFINE)", retries=2, fallback="passthrough")
    def _stage_refine(self, input_wav):
        return self.refiner.process(input_wav)

    @RetryEngine.resilient_stage("DENOISE (GS-CRYSTAL)", retries=3, fallback="cpu_retry")
    def _stage_denoise(self, input_wav, stage="pre-diffusion"):
        return self.denoiser.process(input_wav, stage=stage)

    @RetryEngine.resilient_stage("UPSCALE (GS-ASCEND)", retries=2, fallback="passthrough")
    def _stage_upscale(self, input_wav, target_sr=48000):
        return self.upscaler.super_resolve(input_wav, target_sr=target_sr)

    @RetryEngine.resilient_stage("MASTER (Pedalboard)", retries=2, fallback="passthrough")
    def _stage_master(self, input_wav, width=0.50, lowpass_hz=20000.0, highpass_hz=19.0, vocal_presence_db=0.0):
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

        # ── Per-run temp file manager ─────────────────────────────────
        self._temp_manager = TempFileManager()
        # (Re-)create decoder with this run's temp manager
        self.decoder = AudioDecoder(temp_manager=self._temp_manager)
        # Invalidate lazy-loaded modules so they pick up the new temp_manager
        self._separator = None
        self._refiner   = None
        self._limiter   = None

        # Apply params — invalidate only what changed
        mode     = params.get('denoise_mode', 'HIGH')
        steps    = int(params.get('denoise_steps', 16))
        strength = float(params.get('denoise_strength', 0.55))
        if steps != self._denoise_steps or strength != self._denoise_strength:
            self._denoise_steps    = steps
            self._denoise_strength = strength
            self._denoiser = None
        if mode != self._mode:
            self._mode = mode
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
                print(">> [1/7] Import buffer hit — skipping FFmpeg decode.")
            else:
                cached = self.cache.get(job_key, "01_ingest")
                if cached:
                    working_wav = cached
                else:
                    print(">> [1/7] Executing FFMPEG Decoder Extraction...")
                    working_wav = self.decoder.decode_to_wav(input_path)
                    self.cache.put(job_key, "01_ingest", working_wav)
                self.cache.put(ingest_key, "01_ingest", working_wav)
            print(f"   ⏱ Ingest: {time.perf_counter() - t0:.2f}s")

            # ── ADAPTIVE CHUNKING GATE ──────────────────────────────────
            # If the ingested audio is long (>5 min), split it into adaptive
            # chunks with the sliding-window chunker. Each chunk runs through
            # stages 2-6 independently, then everything is reassembled.
            chunker = AdaptiveChunker(temp_manager=self._temp_manager)
            split_result = chunker.split(working_wav)
            chunk_paths = split_result["chunk_paths"]
            should_chunk = split_result["should_chunk"]

            if should_chunk:
                num = len(chunk_paths)
                print(f">> [CHUNKER] Long file detected — splitting into {num} adaptive chunks")
                print(f">> [CHUNKER] Processing chunks horizontally to optimize RAM...")
                
                assembled_parts = self._process_chunks_horizontally(chunk_paths, params, job_key, num)

                # Reassemble with crossfade stitching
                chunker.assemble(assembled_parts, output_path)
                chunker.cleanup()

                total = time.perf_counter() - pipeline_start
                self.cache.summary()
                print(f"\n{'='*60}")
                print(f"  ✓ Restoration Complete ({num} chunks) → {os.path.basename(output_path)}")
                print(f"  Total Pipeline Time: {total:.2f}s")
                print(f"{'='*60}\n")
                return True

            # ── STEP 2/7 · SEPARATE (Transformer) ─────────────────────
            t0 = time.perf_counter()
            vocal_wav = self._cached_stage(
                job_key, "02_separate",
                lambda: self._stage_separate(working_wav),
                ">> [2/7] GS-PRISM Voice Isolation (BS-RoFormer)...",
            )
            self._free_model('_separator', 'Separate')
            print(f"   ⏱ Separate: {time.perf_counter() - t0:.2f}s")

            # ── STEP 3/7 · REFINE (Diffusion) ────────────────────────────
            t0 = time.perf_counter()
            refined_wav = self._cached_stage(
                job_key, "03_refine",
                lambda: self._stage_refine(vocal_wav),
                ">> [3/7] GS-REFINE Diffusion Refinement (Diff-HierVC)...",
            )
            self._free_model('_refiner', 'Refine')
            print(f"   ⏱ Refine: {time.perf_counter() - t0:.2f}s")

            # ── STEP 4/7 · ANALYZE ──────────────────────────────────────
            t0 = time.perf_counter()
            print(">> [4/7] Spectrum Analysis & Noise Profiling...")
            noise_profile = self.profiler.analyze(refined_wav)
            try:
                auto_eq = type(self.profiler).compute_auto_eq(noise_profile)
            except Exception as eq_err:
                print(f"[WARNING] Auto-EQ computation failed: {eq_err}")
                auto_eq = _DEFAULT_AUTO_EQ
            # Emit structured line so the UI can parse and display it
            print(
                f"[NoiseProfiler] Auto-EQ: "
                f"HPF={int(auto_eq.get('highpass_hz', 20))}Hz | "
                f"LPF={int(auto_eq.get('lowpass_hz', 20000))}Hz | "
                f"Vocal={auto_eq.get('vocal_presence_db', 0.0):+.1f}dB"
            )
            print(f"   ⏱ Analyze: {time.perf_counter() - t0:.2f}s")

            # ── STEP 5/7 · DENOISE (Transformer-Diffusion) ──────────────
            t0 = time.perf_counter()
            enhanced_wav_1 = self._cached_stage(
                job_key, "05_denoise",
                lambda: self._stage_denoise(refined_wav, stage="pre-diffusion"),
                ">> [5/7] GS-CRYSTAL Neural Restoration (VoiceRestore)...",
            )
            print(f"   ⏱ Denoise: {time.perf_counter() - t0:.2f}s")

            # ── STEP 6/7 · UPSCALE (Diffusion SR) ────────────────────────
            # Post-diffusion cleanup FIRST, then free denoiser, then upscale
            t0 = time.perf_counter()
            enhanced_wav_post = self._cached_stage(
                job_key, "05_denoise_post",
                lambda: self._stage_denoise(enhanced_wav_1, stage="post-diffusion"),
                ">> [5/7] GS-CRYSTAL Post-Diffusion Cleanup...",
            )
            self._free_model('_denoiser', 'Denoise')

            enhanced_wav_2 = self._cached_stage(
                job_key, "06_upscale",
                lambda: self._stage_upscale(enhanced_wav_post, target_sr=48000),
                ">> [6/7] GS-ASCEND Latent Diffusion Upscale (AudioSR)...",
            )
            self._free_model('_upscaler', 'Upscale')
            print(f"   ⏱ Upscale: {time.perf_counter() - t0:.2f}s")

            # ── STEP 7/7 · MASTER (Polishing) ────────────────────────────
            t0 = time.perf_counter()
            width = float(params['stereo_width'])
            mastered_wav = self._cached_stage(
                job_key, "07_master",
                lambda: self._stage_master(
                    enhanced_wav_2,
                    width=width,
                    lowpass_hz=auto_eq.get('lowpass_hz', 20000.0),
                    highpass_hz=auto_eq.get('highpass_hz', 20.0),
                    vocal_presence_db=auto_eq.get('vocal_presence_db', 0.0),
                ),
                ">> [7/7] Pedalboard AI Mastering & Auto-EQ...",
            )
            self._free_model('_limiter', 'Master')
            print(f"   ⏱ Master: {time.perf_counter() - t0:.2f}s")

            # ── EXPORT ──────────────────────────────────────────────────
            t0 = time.perf_counter()
            print(">> Finalizing Export — multiplexing output...")
            self.decoder.finalize_export(mastered_wav, input_path, output_path,
                                         fmt=params.get('output_format', 'WAV'))
            print(f"   ⏱ Export: {time.perf_counter() - t0:.2f}s")

            total = time.perf_counter() - pipeline_start
            self.cache.summary()
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
        """Purges the .temp/<job_id>/ working directory after a successful run."""
        if self._temp_manager:
            self._temp_manager.cleanup()
        # Also clean up legacy trinity_temp/ if it still exists
        TempFileManager.cleanup_legacy()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    # PyInstaller + multiprocessing.freeze_support(): child processes re-execute
    # this entry point with special flags (-B -S -I -c "from multiprocessing...").
    # Guard against child processes re-parsing CLI args by checking sys.argv.
    if len(sys.argv) > 1 and sys.argv[1] in ("-B", "-c"):
        # This is a multiprocessing child — do nothing (freeze_support handled it).
        sys.exit(0)

    # ── Model management commands (no ML imports needed) ────────────────
    if len(sys.argv) > 1 and sys.argv[1] == "--check-models":
        from model_registry import check_all_models
        import json as _json
        status = check_all_models()
        if "--json" in sys.argv:
            print(_json.dumps(status))
        else:
            print(f"All installed: {status['all_installed']}")
            for m in status['models']:
                icon = "OK" if m['installed'] else "MISSING"
                print(f"  [{icon}] {m['name']} ({m['size_mb']}MB)")
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--download-models":
        from model_downloader import download_all_models
        result = download_all_models()
        sys.exit(0 if result["success"] else 1)

    parser = argparse.ArgumentParser(
        description="VOXIS V4.0.0 DENSE — Trinity V8.2 Backend | Glass Stone LLC © 2026"
    )
    parser.add_argument("--input",        required=True,  help="Input audio/video file path")
    parser.add_argument("--output",       required=True,  help="Output file path")
    parser.add_argument("--extreme",           action="store_true", help="Use EXTREME denoise mode")
    parser.add_argument("--stereo-width",      type=float, default=0.50,
                        help="Stereo width 0.0–1.0 (default 0.50)")
    parser.add_argument("--format",            default="WAV", choices=["WAV", "FLAC", "MP3", "WAV24", "WAV32", "ALAC"],
                        help="Output format: WAV (default), FLAC, MP3, WAV24, WAV32, ALAC")
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
