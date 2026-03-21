import os
import hashlib
import shutil
import time
import json

class PipelineCache:
    """
    SHA-256 stage caching system for the Trinity V8.1 pipeline.
    Stores intermediate WAV outputs keyed by input file hash + params.
    Re-running the same file skips completed stages instantly.
    Stale caches older than TTL_SECONDS are purged on init.
    Cache is capped at MAX_SIZE_GB to prevent disk bloat.
    """
    TTL_SECONDS = 86400  # 24 hours
    MAX_SIZE_GB = 8.0    # 8 GB max cache size

    def __init__(self):
        home_dir = os.path.expanduser("~")
        self.cache_dir = os.path.join(home_dir, ".voxis", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._purge_stale()
        self._enforce_size_limit()
        print(f"[PipelineCache] Initialized → {self.cache_dir}")

    # ── Public API ──────────────────────────────────────────────────────

    def make_ingest_key(self, input_path: str) -> str:
        """
        Zero-I/O import buffer key derived from file metadata (path + size + mtime).
        Used as a fast pre-check before the ingest/decode stage to avoid reading
        the file at all on cache hits — critical for large audio/video files.
        """
        stat = os.stat(input_path)
        key_str = f"{os.path.abspath(input_path)}|{stat.st_size}|{stat.st_mtime}"
        return "ib_" + hashlib.sha256(key_str.encode()).hexdigest()[:13]

    def make_job_key(self, input_path: str, params: dict) -> str:
        """
        Creates a deterministic hash from file stat metadata (path + size + mtime)
        plus the serialized pipeline parameters. Zero file I/O — stat only.
        """
        stat = os.stat(input_path)
        key_str = f"{os.path.abspath(input_path)}|{stat.st_size}|{stat.st_mtime}"
        param_str = json.dumps(params, sort_keys=True)
        combined = key_str + "|" + param_str
        return "jk_" + hashlib.sha256(combined.encode()).hexdigest()[:13]

    def get(self, job_key: str, stage: str) -> str | None:
        """
        Returns the cached WAV path for a given stage, or None on miss.
        Validated: cached file must exist on disk and be non-empty.
        """
        cached_path = os.path.join(self.cache_dir, f"{job_key}_{stage}.wav")
        if os.path.exists(cached_path):
            if os.path.getsize(cached_path) > 0:
                print(f"[PipelineCache] ⚡ CACHE HIT  → {stage}")
                return cached_path
            else:
                # Corrupt cache entry — remove it
                print(f"[PipelineCache] ⚠ Empty cache file for {stage}, removing.")
                try:
                    os.remove(cached_path)
                except OSError:
                    pass
        return None

    def put(self, job_key: str, stage: str, wav_path: str) -> str:
        """
        Hardlinks the stage output WAV into cache (instant, no data copy).
        Falls back to copy if cross-device or filesystem doesn't support links.
        """
        cached_path = os.path.join(self.cache_dir, f"{job_key}_{stage}.wav")
        try:
            if os.path.exists(cached_path):
                os.remove(cached_path)
            os.link(wav_path, cached_path)
            print(f"[PipelineCache] 💾 CACHED     → {stage}")
        except OSError:
            try:
                shutil.copy2(wav_path, cached_path)
                print(f"[PipelineCache] 💾 CACHED     → {stage} (copy fallback)")
            except Exception as e:
                print(f"[PipelineCache] Cache write failed for {stage}: {e}")
        return cached_path

    def invalidate(self, job_key: str):
        """Removes all cached stages for a specific job key."""
        for fname in os.listdir(self.cache_dir):
            if fname.startswith(job_key):
                os.remove(os.path.join(self.cache_dir, fname))
        print(f"[PipelineCache] Invalidated cache for key {job_key}")

    # ── Internal ────────────────────────────────────────────────────────

    def _enforce_size_limit(self):
        """Evict oldest cache files if total cache exceeds MAX_SIZE_GB."""
        try:
            entries = []
            total_bytes = 0
            for fname in os.listdir(self.cache_dir):
                fpath = os.path.join(self.cache_dir, fname)
                if os.path.isfile(fpath):
                    size = os.path.getsize(fpath)
                    mtime = os.path.getmtime(fpath)
                    entries.append((fpath, size, mtime))
                    total_bytes += size

            max_bytes = int(self.MAX_SIZE_GB * 1024**3)
            if total_bytes <= max_bytes:
                return

            # Sort oldest first, evict until under limit
            entries.sort(key=lambda x: x[2])
            evicted = 0
            for fpath, size, _ in entries:
                if total_bytes <= max_bytes:
                    break
                try:
                    os.remove(fpath)
                    total_bytes -= size
                    evicted += 1
                except OSError:
                    pass
            if evicted:
                remaining_gb = total_bytes / (1024**3)
                print(f"[PipelineCache] Evicted {evicted} files to enforce {self.MAX_SIZE_GB}GB limit ({remaining_gb:.1f}GB remaining)")
        except Exception as e:
            print(f"[PipelineCache] Size limit enforcement failed: {e}")

    def _purge_stale(self):
        """Removes cached files older than TTL_SECONDS."""
        try:
            now = time.time()
            purged = 0
            for fname in os.listdir(self.cache_dir):
                fpath = os.path.join(self.cache_dir, fname)
                if os.path.isfile(fpath):
                    age = now - os.path.getmtime(fpath)
                    if age > self.TTL_SECONDS:
                        try:
                            os.remove(fpath)
                            purged += 1
                        except OSError:
                            pass
            if purged:
                print(f"[PipelineCache] Purged {purged} stale cache entries (>{self.TTL_SECONDS}s old)")
        except Exception as e:
            print(f"[PipelineCache] Purge scan failed: {e}")


# Module-level singleton — initialized on import, shared across all pipeline instances
cache = PipelineCache()
