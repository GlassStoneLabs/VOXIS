import wave
import math
import struct

sample_rate = 44100
duration_seconds = 2.0
frequency = 440.0 # A4
num_samples = int(sample_rate * duration_seconds)

with wave.open("test_input.wav", "w") as wav_file:
    wav_file.setnchannels(2) # Stereo
    wav_file.setsampwidth(2) # 16-bit
    wav_file.setframerate(sample_rate)
    
    for i in range(num_samples):
        # Generate sine wave
        value = int(32767.0 * math.sin(2.0 * math.pi * frequency * i / sample_rate))
        # Pack as 16-bit little-endian (stereo means Left and Right are same here)
        data = struct.pack("<hh", value, value)
        wav_file.writeframesraw(data)

print("test_input.wav created.")
