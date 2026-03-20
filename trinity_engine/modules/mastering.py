import os
import soundfile as sf
from pedalboard import Pedalboard, Limiter, Compressor

class PhaseLimiter:
    """
    Stage 5: Final Mastering & Stereo Expansion
    Utilizes Pedalboard for high-quality limiter and VST grade compressor processing.
    """
    def __init__(self):
        print(f"[{self.__class__.__name__}] Initializing Pedalboard Mastering Engine...")
        self.board = Pedalboard([
            Compressor(threshold_db=-12, ratio=2.5),
            Limiter(threshold_db=-0.5)
        ])

    def apply(self, input_audio_path, width=0.8):
        """
        Loads the file, applies mastering effects via Pedalboard, and expands stereo field if needed.
        """
        print(f"[{self.__class__.__name__}] Applying Limiter and Width ({width})...")
        
        output_dir = os.path.join(os.getcwd(), "trinity_temp")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, "mastered_" + os.path.basename(input_audio_path))
        
        try:
             audio, sr = sf.read(input_audio_path)
             
             # If mono, create stereo pair
             if len(audio.shape) == 1:
                  # Duplicate channel
                  import numpy as np
                  audio = np.stack([audio, audio], axis=-1)
             
             # Apply slight volume boost to mid and alter sides for width
             # simple implementation: Left = L*1+(R*(1-width)), Right = R*1+(L*(1-width))
             w = float(width)
             left = audio[:, 0]
             right = audio[:, 1]
             
             new_left = left * 1.0 + right * (1.0 - w) * 0.5
             new_right = right * 1.0 + left * (1.0 - w) * 0.5
             
             import numpy as np
             widened_audio = np.stack([new_left, new_right], axis=-1)
             
             # Pedalboard expects Channels x Samples (transpose)
             effected = self.board(widened_audio.T, sr)
             
             # Save
             sf.write(out_path, effected.T, sr)
             return out_path
        except Exception as e:
             print(f"[{self.__class__.__name__}] Mastering Failed: {e}")
             return input_audio_path
