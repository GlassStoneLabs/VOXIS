import torch
import torchaudio
import os
from df.enhance import enhance, init_df
from df.io import load_audio, save_audio
from .mps_utils import AppleSiliconOptimizer

class DeepFilterNetWrapper:
    """
    Stage 2: Universal Restoration & Enhancement using Real DeepFilterNet3
    """
    def __init__(self, intensity="High", device=None):
        self.intensity = intensity
        self.device = device if device else AppleSiliconOptimizer.initialize_device()
             
        print(f"[{self.__class__.__name__}] Initializing DeepFilterNet3 on {self.device}...")
        
        # init_df automatically downloads the latest weights if not present
        try:
            self.model, self.df_state, _ = init_df()
        except Exception as e:
            print(f"[{self.__class__.__name__}] df initialization error {e}")
            self.model = None

    def enhance(self, input_audio_path, noise_profile, attenuation_db=48):
        """
        Applies Universal Restoration using DFN3 API.
        Takes and returns a file path for the orchestrator chain.
        """
        print(f"[{self.__class__.__name__}] Running DeepFilterNet3 Inference...")
        
        output_dir = os.path.join(os.getcwd(), "trinity_temp")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, "denoised_" + os.path.basename(input_audio_path))
        
        if not self.model:
            print(f"[{self.__class__.__name__}] Model missing. Skipping denoising.")
            return input_audio_path
            
        try:
            # 1. Load Audio
            audio, sr = load_audio(input_audio_path, sr=self.df_state.sr())
            
            # 2. Inference
            if self.intensity == "EXTREME" or attenuation_db > 60:
                 print(f"[{self.__class__.__name__}] EXTREME Mode Engaged - Applying attenuation_limit={attenuation_db}dB.")
                 enhanced = enhance(self.model, self.df_state, audio, atten_lim_db=attenuation_db)
            else:
                 enhanced = enhance(self.model, self.df_state, audio, atten_lim_db=48)
                 
            # 3. Save
            save_audio(out_path, enhanced, sr)
            return out_path
            
        except Exception as e:
            print(f"[{self.__class__.__name__}] Denoise Failed: {e}")
            return input_audio_path
