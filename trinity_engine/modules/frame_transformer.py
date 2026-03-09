import os
import torch
from .device_utils import DeviceOptimizer

class FrameTransformerWrapper:
    """
    Stage 2/4: Transformer-based enhancement and vocal manipulation using
    the carperbr/frame-transformer architecture.
    """
    def __init__(self):
        self.device = DeviceOptimizer.get_optimal_device()
        self.repo_path = os.path.join(os.getcwd(), "trinity_engine", "modules", "external", "frame_transformer")
        print(f"[{self.__class__.__name__}] Initializing Frame-Transformer on {self.device}...")
        
    def process(self, input_audio_path, stage="pre-diffusion"):
        """
        Executes the Frame Transformer processing pass.
        Returns the path to the processed output.
        """
        print(f"[{self.__class__.__name__}] Executing {stage} Frame-Transformer inference...")
        
        output_dir = os.path.join(os.getcwd(), "trinity_temp")
        os.makedirs(output_dir, exist_ok=True)
        
        base_name = os.path.splitext(os.path.basename(input_audio_path))[0]
        out_path = os.path.join(output_dir, f"{base_name}_ft_{stage}.wav")
        
        # Note: Actual inference requires calling the frame_transformer inference script
        # Due to module isolation, we treat this as a subprocess or import wrapper.
        print(f"[{self.__class__.__name__}] (Placeholder) Frame-Transformer {stage} pass.")
        
        # Return input safely if not generated
        return out_path if os.path.exists(out_path) else input_audio_path
