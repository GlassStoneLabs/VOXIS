import os
import sys

def get_engine_base_dir():
    """Return a WRITABLE base directory for model downloads, caches, and temp files.
    When frozen (installed .app), the bundle is read-only on macOS, so we use ~/.voxis/.
    When running from source, we use the project root (trinity_engine/).
    """
    if getattr(sys, 'frozen', False):
        # Installed app — bundle is read-only; use user-writable directory
        writable = os.path.join(os.path.expanduser("~"), ".voxis")
        os.makedirs(writable, exist_ok=True)
        return writable
    else:
        # Running from standard python source tree (relative to modules/path_utils.py)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
