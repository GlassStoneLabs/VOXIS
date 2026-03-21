# -*- mode: python ; coding: utf-8 -*-
# VOXIS V4.0.0 DENSE — Trinity V8.1 PyInstaller Spec (Windows x64)
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Build requirements (run on Windows):
#   pip install "setuptools==69.5.1" "numpy<2.0"
#   pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
#   pip install -r requirements_win.txt pyinstaller
#   pyinstaller --noconfirm --clean trinity_v8_core_win.spec

import os
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

hiddenimports = [
    # PyTorch / torchaudio (CUDA + CPU — no MPS on Windows)
    'torch', 'torchaudio', 'torchaudio.transforms', 'torchaudio.functional',
    'torchaudio.backend', 'torchaudio.io',
    'torch.nn', 'torch.nn.functional',
    'torch.cuda', 'torch.cuda.amp',
    'torch.utils.data',
    # Audio processing
    'librosa', 'librosa.core', 'librosa.feature', 'librosa.effects',
    'librosa.util', 'librosa.filters',
    'soundfile',
    'numpy', 'numpy.core', 'numpy.random',
    'scipy', 'scipy.signal', 'scipy.fftpack', 'scipy.io', 'scipy.io.wavfile',
    # DeepFilterNet
    'df', 'df.enhance', 'df.io', 'df.model', 'df.config', 'df.logger',
    # audio-separator (all architecture backends required at runtime)
    'audio_separator', 'audio_separator.separator',
    'audio_separator.separator.architectures',
    'audio_separator.separator.architectures.mdxc_separator',
    'audio_separator.separator.architectures.mdx_separator',
    'audio_separator.separator.architectures.vr_separator',
    'audio_separator.separator.architectures.demucs_separator',
    # AudioSR (latent diffusion upsampler)
    'audiosr', 'audiosr.pipeline', 'audiosr.lowpass',
    'audiosr.clap', 'audiosr.latent_diffusion',
    'audiosr.utils',
    # Pedalboard
    'pedalboard', 'pedalboard._pedalboard',
    # HuggingFace / transformers
    'transformers', 'transformers.modeling_utils',
    'huggingface_hub', 'huggingface_hub.utils',
    'tokenizers',
    'einops', 'omegaconf', 'yaml',
    'packaging', 'packaging.version',
    'filelock', 'requests', 'urllib3', 'certifi',
    # System / Cross-platform
    'psutil', 'platform', 'hashlib', 'contextlib',
    # ONNX + DirectML (Windows GPU acceleration)
    'onnx', 'onnx.checker', 'onnx.numpy_helper', 'onnx.helper',
    'onnxruntime', 'onnxruntime.capi', 'onnxruntime.capi._pybind_state',
    # Voxis pipeline modules (v8.1 resilient backend)
    'modules.ingest',
    'modules.device_utils',
    'modules.path_utils',
    'modules.onnx_bridge',
    'modules.coreml_bridge',
    'modules.adaptive_chunker',
    'modules.uvr_processor',
    'modules.spectrum_analyzer',
    'modules.voicerestore_wrapper',
    'modules.upsampler',
    'modules.mastering_phase',
    'modules.error_telemetry',
    'modules.pipeline_cache',
    'modules.retry_engine',
    # VoiceRestore
    'model', 'BigVGAN', 'bigvgan', 'voice_restore',
    'pkg_resources',
]

datas = [
    ('trinity_engine/modules/external', 'modules/external'),
]
try:
    datas += collect_data_files('df', includes=['**/*.onnx', '**/*.pt', '**/*.yaml'])
except Exception:
    pass
try:
    datas += collect_data_files('x_transformers', includes=['**/*.py'])
    datas += collect_data_files('gateloop_transformer', includes=['**/*.py'])
except Exception:
    pass
try:
    datas += collect_data_files('librosa', includes=['**/*'])
except Exception:
    pass
try:
    datas += collect_data_files('audio_separator', includes=['**/*'])
except Exception:
    pass
try:
    datas += collect_data_files('audiosr', includes=['**/*'])
except Exception:
    pass
try:
    datas += collect_data_files('language_tags', includes=['**/*'])
except Exception:
    pass

binaries = []
try:
    binaries += collect_dynamic_libs('numba')
    binaries += collect_dynamic_libs('llvmlite')
except Exception:
    pass
# DirectML DLL (Windows GPU acceleration)
try:
    binaries += collect_dynamic_libs('onnxruntime')
except Exception:
    pass

a = Analysis(
    ['trinity_engine/trinity_core.py'],
    pathex=[
        os.path.abspath('trinity_engine'),
        os.path.abspath('trinity_engine/modules'),
        os.path.abspath('trinity_engine/modules/external/voicerestore'),
        os.path.abspath('trinity_engine/modules/external/voicerestore/BigVGAN'),
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'cv2', 'PIL', 'flask',
        'jupyter', 'notebook', 'IPython', 'wx',
        # macOS-only — not available on Windows
        'torch.backends.mps',
        'coremltools',
    ],
    noarchive=False,
    optimize=0,  # 0 retains assert statements and docstrings (required for TorchScript)
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='trinity_v8_core',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app/src-tauri/icons/icon.ico',
    # Output: trinity_v8_core.exe
)
