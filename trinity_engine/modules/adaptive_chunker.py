# VOXIS V4.0.0 DENSE — Adaptive Sliding-Window Chunker
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Breaks long audio/video into adaptive-length chunks for pipeline processing.
# Each chunk runs through the full restoration pipeline independently,
# then all processed chunks are reassembled with crossfade stitching.
#
# Chunk range: 30 seconds → 5 minutes (adaptive based on duration + RAM)
# Overlap: 3–10 seconds (linear crossfade for seamless joins)
# Storage: ~/.voxis/chunks/<job_id>/
#
# Sliding window architecture:
#   Input WAV ──→ split() ──→ [chunk_0, chunk_1, ..., chunk_N]
#                                    ↓ (each through full pipeline)
#   [proc_0, proc_1, ..., proc_N] ──→ assemble() ──→ final WAV

import os
import uuid
import math
import torch
import torchaudio

from .path_utils import get_engine_base_dir
from .device_utils import DeviceOptimizer


# ── Chunk sizing presets (all in seconds) ─────────────────────────────────────

MIN_CHUNK_SEC  = 60    # Fixed 60s chunk length
NO_CHUNK_THRESHOLD = 300  # Default duration threshold (5 min)

def compute_chunk_params(wav_path: str, duration_sec: float, ram_available_gb: float = 8.0) -> dict:
    """
    Compute optimal chunk size based on system resources and file size.
    Trigger chunking if file is over 200MB OR if duration > 5 min.
    Always uses 60-second chunks with small overlap for crossfading.
    """
    file_size_mb = os.path.getsize(wav_path) / (1024 * 1024)
    should_chunk = file_size_mb > 200.0 or duration_sec > NO_CHUNK_THRESHOLD
    
    # If system RAM is critically low (< 4GB), force chunking regardless of size
    if ram_available_gb < 4.0 and duration_sec > 60:
        should_chunk = True

    if not should_chunk:
        return {
            "chunk_sec":    duration_sec,
            "overlap_sec":  0,
            "num_chunks":   1,
            "should_chunk": False,
        }

    chunk_sec = MIN_CHUNK_SEC
    overlap_sec = 5  # 5 second overlap for smooth stitching

    # Compute number of chunks
    stride = chunk_sec - overlap_sec
    num_chunks = max(1, math.ceil((duration_sec - overlap_sec) / stride))

    return {
        "chunk_sec":    chunk_sec,
        "overlap_sec":  overlap_sec,
        "num_chunks":   num_chunks,
        "should_chunk": True,
    }


class AdaptiveChunker:
    """
    Sliding-window chunker for long audio processing.

    Usage:
        chunker = AdaptiveChunker()
        result = chunker.split(wav_path)
        if result["should_chunk"]:
            for chunk_path in result["chunk_paths"]:
                processed = pipeline.process(chunk_path)
                processed_chunks.append(processed)
            final = chunker.assemble(processed_chunks, output_path)
    """

    def __init__(self, job_id: str = None, temp_manager=None):
        self.job_id = job_id or str(uuid.uuid4())[:12]
        self._temp_manager = temp_manager
        if temp_manager:
            # Use the structured .temp/<job_id>/chunks/ directory
            self.chunks_dir = temp_manager.get_stage_dir("chunks")
        else:
            base_dir = get_engine_base_dir()
            # Fallback: standalone .temp/<own_job_id>/ for backward compat
            self.chunks_dir = os.path.join(base_dir, ".temp", self.job_id)
        os.makedirs(self.chunks_dir, exist_ok=True)
        self._metadata = {}

    def split(self, wav_path: str, ram_gb: float = 8.0) -> dict:
        """
        Split a WAV file into adaptive-length chunks with overlap.

        Args:
            wav_path: Path to the ingested WAV file (44.1kHz stereo)
            ram_gb: Available RAM in GB (used for chunk sizing)

        Returns:
            dict with keys:
                should_chunk: bool — False if file is short enough for single pass
                chunk_paths: list[str] — paths to chunk WAV files in temp dir
                params: dict — chunk_sec, overlap_sec, num_chunks
                source_sr: int — original sample rate
                source_channels: int — original channel count
        """
        # Load metadata without loading full audio
        info = torchaudio.info(wav_path)
        sr = info.sample_rate
        num_frames = info.num_frames
        channels = info.num_channels
        duration_sec = num_frames / sr

        # Get system memory directly or use passed ram_gb
        mem = DeviceOptimizer.get_memory_info()
        available_ram = mem.get("system_ram_available_gb", ram_gb)

        file_size_mb = os.path.getsize(wav_path) / (1024 * 1024)
        print(f"[AdaptiveChunker] Input: {duration_sec:.1f}s | {sr}Hz | {channels}ch | ~{file_size_mb:.1f}MB")

        params = compute_chunk_params(wav_path, duration_sec, available_ram)

        if not params["should_chunk"]:
            print(f"[AdaptiveChunker] Duration under {NO_CHUNK_THRESHOLD}s — single pass (no chunking)")
            return {
                "should_chunk":    False,
                "chunk_paths":     [wav_path],
                "params":          params,
                "source_sr":       sr,
                "source_channels": channels,
            }

        chunk_sec   = params["chunk_sec"]
        overlap_sec = params["overlap_sec"]
        num_chunks  = params["num_chunks"]
        stride_sec  = chunk_sec - overlap_sec

        print(f"[AdaptiveChunker] Splitting → {num_chunks} chunks "
              f"({chunk_sec}s each, {overlap_sec}s overlap, {stride_sec}s stride)")

        chunk_samples   = int(chunk_sec * sr)
        overlap_samples = int(overlap_sec * sr)
        stride_samples  = chunk_samples - overlap_samples

        chunk_paths = []
        for i in range(num_chunks):
            start = i * stride_samples
            end   = min(start + chunk_samples, num_frames)
            length = end - start

            # Load just this chunk from disk (memory efficient)
            audio, _ = torchaudio.load(wav_path, frame_offset=start, num_frames=length)

            chunk_path = os.path.join(self.chunks_dir, f"chunk_{i:04d}.wav")
            torchaudio.save(chunk_path, audio, sr)
            chunk_paths.append(chunk_path)

            chunk_dur = length / sr
            print(f"[AdaptiveChunker] Chunk {i+1}/{num_chunks}: "
                  f"{start/sr:.1f}s–{end/sr:.1f}s ({chunk_dur:.1f}s) → {os.path.basename(chunk_path)}")

            del audio  # Free memory between chunks

        # Store metadata for assembly
        self._metadata = {
            "source_sr":       sr,
            "source_channels": channels,
            "chunk_sec":       chunk_sec,
            "overlap_sec":     overlap_sec,
            "num_chunks":      num_chunks,
            "overlap_samples": overlap_samples,
        }

        return {
            "should_chunk":    True,
            "chunk_paths":     chunk_paths,
            "params":          params,
            "source_sr":       sr,
            "source_channels": channels,
        }

    def assemble(self, processed_paths: list, output_path: str,
                 target_sr: int = None) -> str:
        """
        Reassemble processed chunks into a single output WAV with crossfade stitching.

        The crossfade uses a linear fade to seamlessly blend the overlap regions
        between adjacent chunks, preventing clicks or phase artifacts at boundaries.

        Args:
            processed_paths: Ordered list of processed chunk WAV paths
            output_path: Final output WAV path
            target_sr: Expected sample rate of processed chunks (auto-detected if None)

        Returns:
            Path to the assembled output WAV
        """
        if len(processed_paths) == 0:
            raise ValueError("[AdaptiveChunker] No chunks to assemble")

        if len(processed_paths) == 1:
            # Single chunk — just copy/rename
            import shutil
            shutil.copy2(processed_paths[0], output_path)
            print(f"[AdaptiveChunker] Single chunk → {output_path}")
            return output_path

        print(f"[AdaptiveChunker] Assembling {len(processed_paths)} processed chunks...")

        # Load first chunk to determine sample rate and channels
        first_audio, first_sr = torchaudio.load(processed_paths[0])
        sr = target_sr or first_sr

        # Determine overlap in the processed audio's sample rate
        # The overlap_sec is from the original split; processed chunks may have
        # a different sample rate (e.g. 48kHz after upscale vs 44.1kHz source)
        overlap_sec = self._metadata.get("overlap_sec", 5)
        overlap_samples = int(overlap_sec * sr)

        print(f"[AdaptiveChunker] Assembly SR: {sr}Hz | Overlap: {overlap_sec}s ({overlap_samples} samples)")

        # Start with first chunk
        assembled = first_audio
        del first_audio

        for i in range(1, len(processed_paths)):
            next_audio, next_sr = torchaudio.load(processed_paths[i])

            # Resample if sample rates don't match
            if next_sr != sr:
                resampler = torchaudio.transforms.Resample(next_sr, sr)
                next_audio = resampler(next_audio)

            # Match channel count
            if next_audio.shape[0] != assembled.shape[0]:
                if next_audio.shape[0] > assembled.shape[0]:
                    next_audio = next_audio[:assembled.shape[0], :]
                else:
                    next_audio = next_audio.repeat(assembled.shape[0] // next_audio.shape[0] + 1, 1)
                    next_audio = next_audio[:assembled.shape[0], :]

            # Apply crossfade at the overlap boundary
            assembled = self._crossfade_stitch(assembled, next_audio, overlap_samples)

            del next_audio
            print(f"[AdaptiveChunker] Stitched chunk {i+1}/{len(processed_paths)} "
                  f"(total: {assembled.shape[-1]/sr:.1f}s)")

        # Normalize to prevent clipping from crossfade accumulation
        peak = torch.max(torch.abs(assembled))
        if peak > 1.0:
            assembled = assembled / peak
            print(f"[AdaptiveChunker] Peak normalized ({peak:.2f} → 1.0)")

        torchaudio.save(output_path, assembled, sr)
        out_size = os.path.getsize(output_path) / (1024 * 1024)
        duration = assembled.shape[-1] / sr

        print(f"[AdaptiveChunker] [OK] Assembly complete: {duration:.1f}s | "
              f"{sr}Hz | {out_size:.1f} MB → {output_path}")

        return output_path

    @staticmethod
    def _crossfade_stitch(left: torch.Tensor, right: torch.Tensor,
                          overlap_samples: int,
                          _fade_cache: dict = {}) -> torch.Tensor:
        """
        Stitch two audio tensors with an equal-power cosine crossfade.

        Equal-power crossfade (cos²θ + sin²θ = 1) preserves constant energy
        across the stitch region, eliminating the ~3 dB dip that linear
        crossfades produce and preventing phase-cancellation artifacts.

        left:   (..., T_left)
        right:  (..., T_right)
        overlap_samples: number of samples where they overlap

        Returns: (..., T_left + T_right - overlap_samples)
        """
        if overlap_samples <= 0:
            return torch.cat([left, right], dim=-1)

        # Clamp overlap to what's actually available
        overlap = min(overlap_samples, left.shape[-1], right.shape[-1])
        if overlap <= 0:
            return torch.cat([left, right], dim=-1)

        # Reuse cached fade curves when overlap length matches
        if overlap not in _fade_cache:
            # Equal-power cosine crossfade: cos(t) fades out, sin(t) fades in
            # cos²(t) + sin²(t) = 1 at every sample → zero energy fluctuation
            t = torch.linspace(0.0, torch.pi / 2, overlap)
            _fade_cache[overlap] = (torch.cos(t), torch.sin(t))
        fade_out, fade_in = _fade_cache[overlap]

        # Apply crossfade to the overlap region
        left_tail    = left[..., -overlap:] * fade_out
        right_head   = right[..., :overlap] * fade_in
        blended      = left_tail + right_head

        # Concatenate: [left_body | blended | right_body]
        return torch.cat([
            left[..., :-overlap],
            blended,
            right[..., overlap:],
        ], dim=-1)

    def cleanup(self):
        """Remove the temporary chunks directory for this job."""
        import shutil
        if os.path.isdir(self.chunks_dir):
            shutil.rmtree(self.chunks_dir, ignore_errors=True)
            print(f"[AdaptiveChunker] Cleaned up chunks → {self.chunks_dir}")

    def get_chunks_dir(self) -> str:
        return self.chunks_dir
