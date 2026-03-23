# VOXIS V4.0.0 DENSE — GS-REFINE Diff-HierVC Wrapper
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Hierarchical Diffusion Vocal Refinement (post-separation).
# Takes BS-RoFormer isolated vocals and runs self-refinement through
# Diff-HierVC's Transformer+Diffusion pipeline to remove residual
# artifacts and sharpen vocal clarity.
#
# Architecture: Transformer (content enc) → Diffusion (pitch + mel) → Vocoder
# Mode: Self-refinement (source = target = isolated vocal)
# SR: 16 kHz internal, resamples to match input on output
# Weights: ~/.voxis/dependencies/models/diff_hiervc/

import os
import sys
import gc
import torch
import torchaudio
import numpy as np
from torch.nn import functional as F

from .path_utils import get_engine_base_dir
from .device_utils import DeviceOptimizer


# ── Constants ────────────────────────────────────────────────────────────────

DIFF_HIERVC_SR = 16000
HOP_LENGTH = 320
PAD_MULTIPLE = 1280  # n_fft / win_length

# Chunk limits: model memory grows with mel frames; 15s keeps it manageable
MAX_CHUNK_SEC = 15
OVERLAP_SEC = 2

# Diffusion timesteps (reduced from original 30/6 for speed; 12/8 is good quality)
DEFAULT_PITCH_STEPS = 12
DEFAULT_VOICE_STEPS = 8


class DiffHierVCWrapper:
    """
    GS-REFINE: Diff-HierVC vocal self-refinement stage.

    Loads models lazily on first call. Uses the isolated vocal as both
    source and target for self-refinement — the diffusion process cleans
    residual separation artifacts while preserving vocal identity.
    """

    def __init__(self, pitch_steps=DEFAULT_PITCH_STEPS,
                 voice_steps=DEFAULT_VOICE_STEPS, temp_manager=None):
        self.pitch_steps = pitch_steps
        self.voice_steps = voice_steps
        self._temp_manager = temp_manager

        # Lazy-loaded components
        self._model = None
        self._vocoder = None
        self._w2v = None
        self._mel_fn = None
        self._hps = None
        self._device = None

        # Paths
        base = get_engine_base_dir()
        self._weights_dir = os.path.join(base, "dependencies", "models", "diff_hiervc")
        self._ext_dir = os.path.join(
            os.path.dirname(__file__), "external", "diff_hiervc"
        )

    # ── Lazy Loading ─────────────────────────────────────────────────────────

    def _ensure_loaded(self):
        if self._model is not None:
            return

        print("[GS-REFINE] Loading Diff-HierVC models (one-time ~20-40s)...")

        # Device selection
        raw_device = DeviceOptimizer.get_optimal_device()
        dev_str = str(raw_device)

        # Diff-HierVC uses moderate channel counts — safe on MPS
        if dev_str == "mps":
            self._device = "mps"
        elif dev_str.startswith("cuda"):
            self._device = dev_str
        else:
            self._device = "cpu"

        # Add external module path for imports
        if self._ext_dir not in sys.path:
            sys.path.insert(0, self._ext_dir)

        # Load utils from exact path to avoid 'utils' name collisions on sys.path
        import importlib.util
        _utils_path = os.path.join(self._ext_dir, "utils", "utils.py")
        _spec = importlib.util.spec_from_file_location("diff_hiervc_utils", _utils_path)
        _utils_mod = importlib.util.module_from_spec(_spec)
        sys.modules["diff_hiervc_utils"] = _utils_mod
        # Also register as utils.utils so internal imports within diff_hiervc work
        sys.modules["utils"] = type(sys)("utils")
        sys.modules["utils"].__path__ = [os.path.join(self._ext_dir, "utils")]
        sys.modules["utils.utils"] = _utils_mod
        _spec.loader.exec_module(_utils_mod)

        # Load config
        get_hparams_from_file = _utils_mod.get_hparams_from_file
        MelSpectrogramFixed = _utils_mod.MelSpectrogramFixed
        load_checkpoint = _utils_mod.load_checkpoint
        config_path = os.path.join(self._ext_dir, "ckpt", "config_bigvgan.json")
        self._hps = get_hparams_from_file(config_path)

        # Build mel spectrogram extractor
        self._mel_fn = MelSpectrogramFixed(
            sample_rate=self._hps.data.sampling_rate,
            n_fft=self._hps.data.filter_length,
            win_length=self._hps.data.win_length,
            hop_length=self._hps.data.hop_length,
            f_min=self._hps.data.mel_fmin,
            f_max=self._hps.data.mel_fmax,
            n_mels=self._hps.data.n_mel_channels,
            window_fn=torch.hann_window,
        ).to(self._device)

        # Load Wav2vec2 (XLS-R-300M) — frozen feature extractor
        from model.diffhiervc import DiffHierVC, Wav2vec2
        print("[GS-REFINE] Loading XLS-R-300M content encoder...")
        self._w2v = Wav2vec2().to(self._device)

        # Load DiffHierVC model
        print("[GS-REFINE] Loading Diff-HierVC model...")
        self._model = DiffHierVC(
            self._hps.data.n_mel_channels,
            self._hps.diffusion.spk_dim,
            self._hps.diffusion.dec_dim,
            self._hps.diffusion.beta_min,
            self._hps.diffusion.beta_max,
            self._hps,
        ).to(self._device)

        model_path = os.path.join(self._weights_dir, "model_diffhier.pth")
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"[GS-REFINE] Model weights not found: {model_path}\n"
                "Run setup_models.py or download manually."
            )
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
        # Handle both raw state_dict and wrapped checkpoint formats
        state_dict = checkpoint.get("model", checkpoint)
        self._model.load_state_dict(state_dict)
        del checkpoint, state_dict  # Free CPU copies
        self._model.eval()

        # Load BigvGAN vocoder (BigvGAN wraps Generator as .dec)
        print("[GS-REFINE] Loading BigvGAN vocoder...")
        from vocoder.bigvgan import BigvGAN as BigvGANVoc
        segment_size = self._hps.train.segment_size // self._hps.data.hop_length
        # HParams → dict for **kwargs unpacking
        model_kwargs = {k: v for k, v in self._hps.model.items()}
        self._vocoder = BigvGANVoc(
            self._hps.data.n_mel_channels,
            segment_size,
            **model_kwargs,
        ).to(self._device)

        voc_path = os.path.join(self._weights_dir, "voc_bigvgan.pth")
        if not os.path.exists(voc_path):
            raise FileNotFoundError(f"[GS-REFINE] Vocoder weights not found: {voc_path}")
        load_checkpoint(voc_path, self._vocoder, None)
        self._vocoder.eval()
        self._vocoder.dec.remove_weight_norm()

        print(f"[GS-REFINE] ✓ All models loaded on {self._device.upper()}")

    # ── F0 Extraction ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_f0(audio_np, sr=16000):
        """Extract F0 using YAAPT. Returns (f0_raw, f0_norm) numpy arrays."""
        import amfm_decompy.pYAAPT as pYAAPT
        import amfm_decompy.basic_tools as basic

        to_pad = int(20.0 / 1000 * sr) // 2
        f0s = []
        for y in audio_np.astype(np.float64):
            y_pad = np.pad(y.squeeze(), (to_pad, to_pad), "constant", constant_values=0)
            try:
                pitch = pYAAPT.yaapt(
                    basic.SignalObj(y_pad, sr),
                    frame_length=20.0,
                    frame_space=5.0,
                    nccf_thresh1=0.25,
                    tda_frame_length=25.0,
                )
                f0s.append(pitch.samp_values[None, None, :])
            except Exception:
                # Fallback: silent F0 if extraction fails
                n_frames = audio_np.shape[-1] // 80
                f0s.append(np.zeros((1, 1, n_frames), dtype=np.float32))

        f0 = np.vstack(f0s)

        # Raw F0 (log scale)
        f0_raw = f0.copy()
        f0_x = torch.log(torch.FloatTensor(f0_raw + 1))

        # Normalized F0 (z-norm voiced frames)
        ii = f0 != 0
        if ii.any():
            f0[ii] = (f0[ii] - f0[ii].mean()) / (f0[ii].std() + 1e-8)
        f0_norm = torch.FloatTensor(f0)

        return f0_x, f0_norm

    # ── Single-Chunk Inference ───────────────────────────────────────────────

    def _infer_chunk(self, audio_16k: torch.Tensor) -> torch.Tensor:
        """
        Run Diff-HierVC self-refinement on a single chunk of 16kHz mono audio.
        audio_16k: shape [1, samples]
        Returns: refined audio tensor [1, samples] at 16kHz
        """
        device = self._device

        # Pad to multiple of 1280
        p = (audio_16k.shape[-1] // PAD_MULTIPLE + 1) * PAD_MULTIPLE - audio_16k.shape[-1]
        audio_padded = F.pad(audio_16k, (0, p))

        with torch.inference_mode():
            # Mel spectrogram
            src_mel = self._mel_fn(audio_padded.to(device))
            src_length = torch.LongTensor([src_mel.size(-1)]).to(device)

            # Wav2vec2 content features (needs 40-sample padding for alignment)
            w2v_input = F.pad(audio_padded, (40, 40), "reflect").to(device)
            w2v_x = self._w2v(w2v_input)
            del w2v_input  # Free GPU memory immediately

            # F0 extraction (CPU numpy)
            f0_x, f0_norm = self._extract_f0(audio_padded.numpy())
            del audio_padded  # No longer needed
            f0_x = f0_x.to(device)
            f0_norm = f0_norm.to(device)

            # Hierarchical diffusion: pitch prediction → mel prediction
            # Self-refinement: source = target (same audio, same speaker)
            refined_mel = self._model.infer_vc(
                src_mel, w2v_x, f0_norm, f0_x,
                src_length, src_mel, src_length,
                diffpitch_ts=self.pitch_steps,
                diffvoice_ts=self.voice_steps,
            )
            del w2v_x, f0_x, f0_norm, src_mel, src_length  # Free before vocoder

            # Vocoder: mel → waveform
            refined_audio = self._vocoder(refined_mel)
            del refined_mel

        # Remove padding and return on CPU
        original_samples = audio_16k.shape[-1]
        refined_audio = refined_audio.squeeze(0)[:, :original_samples].cpu()

        return refined_audio

    # ── Main Process Entry ───────────────────────────────────────────────────

    def process(self, input_wav_path: str) -> str:
        """
        Apply Diff-HierVC self-refinement to isolated vocals.

        Args:
            input_wav_path: Path to BS-RoFormer separated vocal WAV

        Returns:
            Path to refined vocal WAV (same sample rate as input)
        """
        self._ensure_loaded()

        print(f"[GS-REFINE] Processing: {os.path.basename(input_wav_path)}")
        print(f"[GS-REFINE] Diffusion steps: pitch={self.pitch_steps}, voice={self.voice_steps}")

        # Load input audio
        audio, orig_sr = torchaudio.load(input_wav_path)

        # Convert to mono
        if audio.dim() > 1 and audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)

        # Clamp to prevent clipping artifacts (in-place)
        audio.clamp_(-1.0, 1.0)

        # Resample to 16kHz for Diff-HierVC
        if orig_sr != DIFF_HIERVC_SR:
            audio_16k = torchaudio.functional.resample(
                audio, orig_sr, DIFF_HIERVC_SR, resampling_method="kaiser_window"
            )
            del audio  # Free original-rate audio
        else:
            audio_16k = audio

        duration_sec = audio_16k.shape[-1] / DIFF_HIERVC_SR
        print(f"[GS-REFINE] Input: {duration_sec:.1f}s @ {orig_sr}Hz → resampled to {DIFF_HIERVC_SR}Hz")

        # Process: single pass or chunked
        if duration_sec <= MAX_CHUNK_SEC:
            refined_16k = self._infer_chunk(audio_16k)
        else:
            refined_16k = self._chunked_inference(audio_16k)
        del audio_16k  # Free 16kHz input

        # Resample back to original sample rate
        if orig_sr != DIFF_HIERVC_SR:
            refined = torchaudio.functional.resample(
                refined_16k, DIFF_HIERVC_SR, orig_sr, resampling_method="kaiser_window"
            )
            del refined_16k
        else:
            refined = refined_16k

        # Normalize (in-place)
        peak = refined.abs().max()
        if peak > 0.001:
            refined.mul_(0.999 / peak)

        # Save output
        if self._temp_manager:
            out_dir = self._temp_manager.get_stage_dir("refine")
        else:
            out_dir = os.path.join(get_engine_base_dir(), ".temp", "refine")
            os.makedirs(out_dir, exist_ok=True)

        out_path = os.path.join(out_dir, "gs_refined.wav")
        torchaudio.save(out_path, refined, orig_sr)

        out_size = os.path.getsize(out_path) / (1024 * 1024)
        print(f"[GS-REFINE] ✓ Refined vocal: {refined.shape[-1]/orig_sr:.1f}s | "
              f"{orig_sr}Hz | {out_size:.1f}MB → {os.path.basename(out_path)}")

        # Free GPU memory
        gc.collect()
        if self._device == "mps":
            torch.mps.empty_cache()
        elif "cuda" in str(self._device):
            torch.cuda.empty_cache()

        return out_path

    # ── Chunked Inference ────────────────────────────────────────────────────

    def _chunked_inference(self, audio_16k: torch.Tensor) -> torch.Tensor:
        """Process long audio in overlapping chunks with crossfade stitching.
        Streams each chunk to disk to avoid holding all chunks in RAM simultaneously."""
        total_samples = audio_16k.shape[-1]
        chunk_samples = int(MAX_CHUNK_SEC * DIFF_HIERVC_SR)
        overlap_samples = int(OVERLAP_SEC * DIFF_HIERVC_SR)
        stride_samples = chunk_samples - overlap_samples

        import math
        num_chunks = max(1, math.ceil((total_samples - overlap_samples) / stride_samples))
        print(f"[GS-REFINE] Chunked mode: {num_chunks} chunks "
              f"({MAX_CHUNK_SEC}s each, {OVERLAP_SEC}s overlap)")

        # Stream chunks to temp files to avoid accumulating all in RAM
        if self._temp_manager:
            chunk_dir = os.path.join(self._temp_manager.get_stage_dir("refine"), "_chunks")
        else:
            chunk_dir = os.path.join(get_engine_base_dir(), ".temp", "refine_chunks")
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_paths = []

        for i in range(num_chunks):
            start = i * stride_samples
            end = min(start + chunk_samples, total_samples)
            chunk = audio_16k[:, start:end]

            print(f"[GS-REFINE] Chunk {i+1}/{num_chunks}: "
                  f"{start/DIFF_HIERVC_SR:.1f}s–{end/DIFF_HIERVC_SR:.1f}s")

            refined_chunk = self._infer_chunk(chunk)

            # Save to disk and free RAM
            chunk_path = os.path.join(chunk_dir, f"ref_chunk_{i:04d}.wav")
            torchaudio.save(chunk_path, refined_chunk, DIFF_HIERVC_SR)
            chunk_paths.append(chunk_path)
            del refined_chunk

            # Free GPU/CPU memory between chunks
            gc.collect()
            if self._device == "mps":
                torch.mps.empty_cache()
            elif "cuda" in str(self._device):
                torch.cuda.empty_cache()

        # Reassemble — load only 2 chunks at a time
        assembled = torchaudio.load(chunk_paths[0])[0]
        for i in range(1, len(chunk_paths)):
            next_chunk = torchaudio.load(chunk_paths[i])[0]
            assembled = self._crossfade_stitch(assembled, next_chunk, overlap_samples)
            del next_chunk
            print(f"[GS-REFINE] Stitched chunk {i+1}/{len(chunk_paths)} "
                  f"(total: {assembled.shape[-1]/DIFF_HIERVC_SR:.1f}s)")

        # Clean up temp chunk files
        import shutil
        shutil.rmtree(chunk_dir, ignore_errors=True)

        return assembled

    @staticmethod
    def _crossfade_stitch(left: torch.Tensor, right: torch.Tensor,
                          overlap_samples: int) -> torch.Tensor:
        """Linear crossfade between two audio chunks."""
        if overlap_samples <= 0:
            return torch.cat([left, right], dim=-1)

        overlap = min(overlap_samples, left.shape[-1], right.shape[-1])
        if overlap <= 0:
            return torch.cat([left, right], dim=-1)

        fade_out = torch.linspace(1.0, 0.0, overlap)
        fade_in = torch.linspace(0.0, 1.0, overlap)

        left_tail = left[..., -overlap:] * fade_out
        right_head = right[..., :overlap] * fade_in
        blended = left_tail + right_head

        return torch.cat([
            left[..., :-overlap],
            blended,
            right[..., overlap:],
        ], dim=-1)
