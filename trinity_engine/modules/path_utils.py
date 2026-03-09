import os
import sys

def get_engine_base_dir():
    """Dynamically resolve the base directory for model weights and configuration.
    Supports both Source execution and frozen Tauri macOS App bundle execution.
    """
    if getattr(sys, 'frozen', False):
        executable_dir = os.path.dirname(sys.executable)
        contents_dir = os.path.dirname(executable_dir)
        resources_dir = os.path.join(contents_dir, "Resources")
        
        # If wrapped in a Tauri .app bundle, models are in Contents/Resources/dependencies/models
        if os.path.exists(os.path.join(resources_dir, "dependencies", "models")):
            return resources_dir
            
        # Fallback if just running the compiled binary locally
        return executable_dir
    else:
        # Running from standard python source tree (relative to modules/path_utils.py)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
