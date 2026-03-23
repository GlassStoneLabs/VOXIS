# VOXIS V4.0.0 DENSE — Temp File Manager
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Centralized .temp/<job_id>/ lifecycle manager for all pipeline stages.
# Replaces the flat trinity_temp/ directory with structured, per-job scoping.
# Cross-platform: macOS (M-series) + Windows (x86_64/ARM).
#
# Layout:
#   <base_dir>/.temp/<job_id>/
#       ingest/      — FFmpeg decoded WAV
#       separate/    — GS-PRISM vocal isolation
#       denoise/     — GS-CRYSTAL pre/post diffusion
#       upscale/     — GS-ASCEND super-resolution
#       master/      — Pedalboard mastering
#       chunks/      — AdaptiveChunker split chunks

import os
import uuid
import time
import shutil

from .path_utils import get_engine_base_dir

# Stale job directories older than this are purged on init
STALE_JOB_TTL = 86400  # 24 hours

# Recognized stage subdirectories
STAGE_DIRS = ("ingest", "separate", "denoise", "upscale", "master", "chunks")


class TempFileManager:
    """
    Manages per-job temporary file directories for the Trinity pipeline.

    Each pipeline run gets a unique job_id. All stage modules write their
    intermediate WAVs into structured subdirectories under .temp/<job_id>/.
    After a successful run, cleanup() removes the entire job directory.

    Usage:
        temp = TempFileManager()              # auto-generates job_id
        temp = TempFileManager(job_id="abc")  # explicit job_id

        path = temp.stage_path("ingest", "decoded.wav")
        # → <base_dir>/.temp/<job_id>/ingest/decoded.wav

        temp.cleanup()        # removes this job's temp dir
        TempFileManager.cleanup_all()  # removes ALL .temp contents
    """

    def __init__(self, job_id: str = None):
        self.job_id = job_id or str(uuid.uuid4())[:12]
        self.base_dir = get_engine_base_dir()
        self.temp_root = os.path.join(self.base_dir, ".temp")
        self.job_dir = os.path.join(self.temp_root, self.job_id)

        # Create job directory and all stage subdirs
        for stage in STAGE_DIRS:
            os.makedirs(os.path.join(self.job_dir, stage), exist_ok=True)

        # Purge stale jobs from previous runs on first init
        self._purge_stale_jobs()

        print(f"[TempFileManager] Job {self.job_id} → {self.job_dir}")

    def stage_path(self, stage: str, filename: str) -> str:
        """
        Return the full path for a temp file within a specific stage subdirectory.
        Creates the stage subdir if it doesn't exist (for custom stage names).

        Args:
            stage:    Stage name (e.g. "ingest", "separate", "denoise", "upscale", "master", "chunks")
            filename: Output filename (e.g. "decoded.wav")

        Returns:
            Absolute path: <base_dir>/.temp/<job_id>/<stage>/<filename>
        """
        stage_dir = os.path.join(self.job_dir, stage)
        os.makedirs(stage_dir, exist_ok=True)
        return os.path.join(stage_dir, filename)

    def get_stage_dir(self, stage: str) -> str:
        """Return the directory path for a stage, creating it if needed."""
        stage_dir = os.path.join(self.job_dir, stage)
        os.makedirs(stage_dir, exist_ok=True)
        return stage_dir

    def disk_usage(self) -> dict:
        """Return disk usage of the current job's temp directory in bytes and MB."""
        total_bytes = 0
        file_count = 0
        if os.path.isdir(self.job_dir):
            for dirpath, _dirnames, filenames in os.walk(self.job_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_bytes += os.path.getsize(fp)
                        file_count += 1
                    except OSError:
                        pass
        return {
            "bytes": total_bytes,
            "mb": round(total_bytes / (1024 ** 2), 1),
            "files": file_count,
        }

    def cleanup(self):
        """Remove this job's entire temp directory and report freed space."""
        usage = self.disk_usage()
        if os.path.isdir(self.job_dir):
            shutil.rmtree(self.job_dir, ignore_errors=True)
            print(f"[TempFileManager] Cleaned up job {self.job_id} "
                  f"— freed {usage['mb']}MB ({usage['files']} files)")

    @classmethod
    def cleanup_all(cls):
        """Remove ALL temp job directories. Use on engine shutdown."""
        temp_root = os.path.join(get_engine_base_dir(), ".temp")
        if os.path.isdir(temp_root):
            shutil.rmtree(temp_root, ignore_errors=True)
            print("[TempFileManager] Purged all .temp contents")

    @classmethod
    def cleanup_legacy(cls):
        """Remove the old flat trinity_temp/ directory if it still exists."""
        legacy_dir = os.path.join(get_engine_base_dir(), "trinity_temp")
        if os.path.isdir(legacy_dir):
            shutil.rmtree(legacy_dir, ignore_errors=True)
            print("[TempFileManager] Purged legacy trinity_temp/ directory")

    def _purge_stale_jobs(self):
        """Remove job directories older than STALE_JOB_TTL seconds."""
        if not os.path.isdir(self.temp_root):
            return
        try:
            now = time.time()
            purged = 0
            for entry in os.listdir(self.temp_root):
                job_path = os.path.join(self.temp_root, entry)
                if not os.path.isdir(job_path):
                    continue
                # Skip the current job
                if entry == self.job_id:
                    continue
                try:
                    age = now - os.path.getmtime(job_path)
                    if age > STALE_JOB_TTL:
                        shutil.rmtree(job_path, ignore_errors=True)
                        purged += 1
                except OSError:
                    pass
            if purged:
                print(f"[TempFileManager] Purged {purged} stale job dirs (>{STALE_JOB_TTL}s old)")
        except Exception as e:
            print(f"[TempFileManager] Stale job purge failed: {e}")
