import os
from huggingface_hub import HfApi

api = HfApi()
files = api.list_repo_files(repo_id="jadechoghari/VoiceRestore")
print("Files in jadechoghari/VoiceRestore:", files)
