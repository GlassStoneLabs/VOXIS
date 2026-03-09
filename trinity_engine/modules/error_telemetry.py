import os
import json
import uuid
import time
import threading
from datetime import datetime

class ErrorTelemetryController:
    """
    Background worker that caches pipeline processing errors locally 
    and syncs them to a web API endpoint for remote developer error-correction.
    """
    def __init__(self, api_endpoint="https://api.glass-stone.com/v1/telemetry/errors"):
        self.api_endpoint = api_endpoint
        
        # Calculate root dir properly relative to script
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cache_dir = os.path.join(base_dir, "dependencies", "error_cache")
        self.cache_file = os.path.join(self.cache_dir, "cache.json")
        self._lock = threading.Lock()
        
        # Ensure nested dependencies/error_cache exists
        os.makedirs(self.cache_dir, exist_ok=True)
        self._ensure_cache_file()
                
        # Start the background sync daemon
        self.sync_thread = threading.Thread(target=self._sync_to_web, daemon=True)
        self.sync_thread.start()
        print(f"[ErrorTelemetry] Background sync daemon initialized.")

    def _ensure_cache_file(self):
        """Create or repair the local JSON cache file."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    json.load(f)  # Validate JSON integrity
            else:
                with open(self.cache_file, 'w') as f:
                    json.dump([], f)
        except (json.JSONDecodeError, ValueError):
            # Corrupt JSON — reset it
            print("[ErrorTelemetry] Cache file was corrupt, resetting.")
            with open(self.cache_file, 'w') as f:
                json.dump([], f)

    def log_error(self, stage: str, exception: Exception, metadata: dict = None):
        """
        Logs a failed pipeline stage to the local JSON cache.
        Thread-safe via lock.
        """
        error_payload = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "stage": stage,
            "error_type": type(exception).__name__,
            "message": str(exception)[:500],  # Truncate very long error messages
            "metadata": metadata or {}
        }
        
        with self._lock:
            try:
                data = []
                if os.path.exists(self.cache_file):
                    try:
                        with open(self.cache_file, 'r') as f:
                            data = json.load(f)
                    except (json.JSONDecodeError, ValueError):
                        data = []

                data.append(error_payload)

                # Cap at 100 entries to prevent unbounded growth
                if len(data) > 100:
                    data = data[-100:]

                with open(self.cache_file, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"[ErrorTelemetry] Error safely cached locally -> ID: {error_payload['id'][:8]}")
            except Exception as e:
                print(f"[ErrorTelemetry] Critical failure writing to local cache: {e}")

    def _sync_to_web(self):
        """
        Daemon thread that continuously monitors `cache.json` and 
        POSTs queued errors to the web API endpoint asynchronously.
        """
        while True:
            try:
                time.sleep(60)  # Sleep FIRST to let the app start up

                if not os.path.exists(self.cache_file):
                    continue

                with self._lock:
                    try:
                        with open(self.cache_file, 'r') as f:
                            data = json.load(f)
                    except (json.JSONDecodeError, ValueError):
                        continue
                        
                if not data:
                    continue

                # Lazy-import requests to avoid crash if not installed
                try:
                    import requests
                except ImportError:
                    continue

                try:
                    response = requests.post(
                        self.api_endpoint, 
                        json={"telemetry": data}, 
                        timeout=10
                    )
                    
                    if response.status_code in (200, 201):
                        with self._lock:
                            with open(self.cache_file, 'w') as f:
                                json.dump([], f)
                        print(f"\n[ErrorTelemetry] Background Sync OK — Flushed {len(data)} errors to Web API.")
                except (requests.ConnectionError, requests.Timeout):
                    pass  # Silent fail for network issues
                    
            except Exception:
                pass  # Never let the daemon thread crash

