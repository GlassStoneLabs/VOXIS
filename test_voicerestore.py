import os
import torch
from transformers import AutoModel

os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

print("Downloading and instantiating VoiceRestore...")
try:
    model = AutoModel.from_pretrained("jadechoghari/VoiceRestore", trust_remote_code=True)
    print("Model downloaded and instantiated successfully!")
    print(model)
except Exception as e:
    print(f"Error: {e}")
