import os
import hashlib
import shutil
import time
import json

from .path_utils import get_engine_base_dir

class PipelineCache:
    """
    SHA-256 stage caching system for the Trinity V8.2 pipeline.
    Stores intermediate WAV outputs keyed by input file hash + params.
    Re-running the same file skips completed stages instantly.
    Stale caches older than TTL_SECONDS are purged on init.
    Cache is capped at MAX_SIZE_GB to prevent disk bloat.
    """
    TTL_SECONDS = 86400  # 24 hours
    MAX_SIZE_GB = 4.0    # 4 GB max cache size (reduced from 8GB to prevent disk pressure)

    def __init__(self):
        self.base_dir = get_engine_base_dir()
        self.cache_dir = os.path.join(self.base_dir, ".temp", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        # Session statistics
        self.enabled = True
        self._hits = 0
        self._misses = 0
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

    def make_chunk_key(self, job_key: str, chunk_index: int) -> str:
        """
        Derive a deterministic sub-key for an individual chunk within a job.
        Enables per-chunk caching so a failed 10-chunk job can resume from
        chunk 7 without re-processing chunks 1-6.
        """
        combined = f"{job_key}|chunk_{chunk_index}"
        return "ck_" + hashlib.sha256(combined.encode()).hexdigest()[:13]

    def get(self, job_key: str, stage: str) -> str | None:
        """
        Returns the cached WAV path for a given stage, or None on miss.
        Validated: cached file must exist on disk and be non-empty.
        """
        if not self.enabled:
            return None
        cached_path = os.path.join(self.cache_dir, f"{job_key}_{stage}.wav")
        if os.path.exists(cached_path):
            if os.path.getsize(cached_path) > 0:
                self._hits += 1
                print(f"[PipelineCache] ⚡ CACHE HIT  → {stage}")
                return cached_path
            else:
                # Corrupt cache entry — remove it
                print(f"[PipelineCache] [!] Empty cache file for {stage}, removing.")
                try:
                    os.remove(cached_path)
                except OSError:
                    pass
        self._misses += 1
        return None

    def put(self, job_key: str, stage: str, wav_path: str) -> str:
        """
        Hardlinks the stage output WAV into cache (instant, no data copy).
        Falls back to copy if cross-device or filesystem doesn't support links.
        """
        if not self.enabled:
            return wav_path
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
                
        # ── SLIDING CACHE LOGIC ──
        # Continuously enforce size limits after every write
        self._enforce_size_limit()
        
        return cached_path

    def invalidate(self, job_key: str):
        """Removes all cached stages for a specific job key."""
        for fname in os.listdir(self.cache_dir):
            if fname.startswith(job_key):
                os.remove(os.path.join(self.cache_dir, fname))
        print(f"[PipelineCache] Invalidated cache for key {job_key}")

    def stats(self) -> dict:
        """Return session cache statistics and disk usage."""
        total = self._hits + self._misses
        ratio = (self._hits / total * 100) if total > 0 else 0.0
        disk_bytes = sum(
            os.path.getsize(os.path.join(self.cache_dir, f))
            for f in os.listdir(self.cache_dir)
            if os.path.isfile(os.path.join(self.cache_dir, f))
        )
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_ratio": round(ratio, 1),
            "disk_mb": round(disk_bytes / (1024 ** 2), 1),
            "entries": len([
                f for f in os.listdir(self.cache_dir)
                if os.path.isfile(os.path.join(self.cache_dir, f))
            ]),
        }

    def summary(self):
        """Print a human-readable cache performance report."""
        s = self.stats()
        print(f"[PipelineCache] Session: {s['hits']} hits / {s['misses']} misses "
              f"({s['hit_ratio']}% hit rate) | "
              f"Disk: {s['disk_mb']}MB across {s['entries']} entries")

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
