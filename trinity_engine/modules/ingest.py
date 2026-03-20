# VOXIS V4.0.0 DENSE — INGEST MODULE
# Copyright © 2026 Glass Stone LLC. All Rights Reserved.
# CEO: Gabriel B. Rodriguez
#
# Production-grade FFmpeg ingest with:
#   - Cross-platform FFmpeg binary resolution (bundled or system)
#   - Probe-based input analysis (duration, channels, sample rate, codec)
#   - File size validation (130GB cap)
#   - Platform-aware stereo downmix & normalization
#   - Video → audio extraction with mux-back on export

import os
import sys
import json
import shutil
import subprocess
import uuid
import platform


# ── Resolve FFmpeg binary ────────────────────────────────────────────────────

def _find_ffmpeg():
    """
    Locate the ffmpeg binary across platforms.
    Priority: bundled binary → system PATH → raise.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. Check for a bundled binary next to the engine
    candidates = [
        os.path.join(base_dir, "dependencies", "bin", "ffmpeg"),
        os.path.join(base_dir, "dependencies", "bin", "ffmpeg.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # 2. Check common system paths (macOS GUI apps don't inherit shell PATH)
    common_paths = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for c in common_paths:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    # 3. Fall back to system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    raise FileNotFoundError(
        "FFmpeg not found. Install it via 'brew install ffmpeg' (macOS) "
        "or 'choco install ffmpeg' (Windows), or place it in dependencies/bin/."
    )


def _find_ffprobe():
    """Locate ffprobe binary with same priority as ffmpeg."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_dir, "dependencies", "bin", "ffprobe"),
        os.path.join(base_dir, "dependencies", "bin", "ffprobe.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    common_paths = [
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
    ]
    for c in common_paths:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c

    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe
    return None  # Non-fatal — probe is optional


# ── Constants ────────────────────────────────────────────────────────────────

MAX_FILE_SIZE_BYTES = 130 * 1024 * 1024 * 1024  # 130 GB hard cap
SUPPORTED_EXTENSIONS = {
    '.wav', '.mp3', '.flac', '.aac', '.ogg', '.m4a', '.aiff', '.wma', '.opus',
    '.mp4', '.mov', '.mkv', '.avi', '.webm', '.mts', '.ts',
}
TARGET_SAMPLE_RATE = 44100
TARGET_CHANNELS = 2
TARGET_BIT_DEPTH = "pcm_s16le"


class AudioDecoder:
    """
    Production-grade ingest module.
    Uses FFmpeg to decode any audio/video into a normalized 44.1kHz 16-bit stereo WAV.
    Cross-platform: macOS (M-series), Windows (x86_64), Linux.
    """

    def __init__(self, temp_dir=None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.temp_dir = temp_dir or os.path.join(base_dir, "trinity_temp")
        os.makedirs(self.temp_dir, exist_ok=True)

        # Resolve binaries once at init
        self.ffmpeg = _find_ffmpeg()
        self.ffprobe = _find_ffprobe()

        print(f"[{self.__class__.__name__}] FFmpeg:  {self.ffmpeg}")
        print(f"[{self.__class__.__name__}] FFprobe: {self.ffprobe or 'not found (probe disabled)'}")
        print(f"[{self.__class__.__name__}] Temp:    {self.temp_dir}")
        print(f"[{self.__class__.__name__}] Platform: {platform.system()} {platform.machine()}")
        print(f"[{self.__class__.__name__}] Max file size: {MAX_FILE_SIZE_BYTES / (1024**3):.0f} GB")

    # ── Probe ────────────────────────────────────────────────────────────

    def probe(self, input_path: str) -> dict:
        """
        Analyze the input file using ffprobe. Returns metadata dict.
        Falls back gracefully if ffprobe is unavailable.
        """
        if not self.ffprobe:
            return {"probed": False, "reason": "ffprobe not available"}

        cmd = [
            self.ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            streams = data.get("streams", [])

            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
            video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

            info = {
                "probed": True,
                "duration_sec": float(fmt.get("duration", 0)),
                "file_size_bytes": int(fmt.get("size", 0)),
                "format_name": fmt.get("format_name", "unknown"),
                "has_video": video_stream is not None,
                "has_audio": audio_stream is not None,
            }

            if audio_stream:
                info["audio_codec"] = audio_stream.get("codec_name", "unknown")
                info["audio_sample_rate"] = int(audio_stream.get("sample_rate", 0))
                info["audio_channels"] = int(audio_stream.get("channels", 0))
                info["audio_bit_rate"] = audio_stream.get("bit_rate", "unknown")

            return info
        except Exception as e:
            return {"probed": False, "reason": str(e)}

    # ── Validation ───────────────────────────────────────────────────────

    def validate(self, input_path: str) -> tuple:
        """
        Validate the input file before processing.
        Returns (is_valid: bool, error_message: str | None).
        """
        if not os.path.exists(input_path):
            return False, f"File not found: {input_path}"

        ext = os.path.splitext(input_path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return False, f"Unsupported format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"

        file_size = os.path.getsize(input_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            gb = file_size / (1024 ** 3)
            return False, f"File too large ({gb:.1f} GB). Maximum: {MAX_FILE_SIZE_BYTES / (1024**3):.0f} GB"

        if file_size == 0:
            return False, "File is empty (0 bytes)"

        return True, None

    # ── Decode ───────────────────────────────────────────────────────────

    def decode_to_wav(self, input_path: str) -> str:
        """
        Decode any audio/video file into a standardized WAV via FFmpeg.
        Output: 44.1kHz, 16-bit, stereo PCM WAV.
        """
        # Validate first
        is_valid, error = self.validate(input_path)
        if not is_valid:
            raise ValueError(error)

        # Probe for diagnostics
        probe_info = self.probe(input_path)
        if probe_info.get("probed"):
            dur = probe_info.get("duration_sec", 0)
            sr = probe_info.get("audio_sample_rate", "?")
            ch = probe_info.get("audio_channels", "?")
            codec = probe_info.get("audio_codec", "?")
            has_video = probe_info.get("has_video", False)
            print(f"[{self.__class__.__name__}] Probe: {dur:.1f}s | {sr}Hz | {ch}ch | {codec}"
                  f"{' | VIDEO DETECTED' if has_video else ''}")
        else:
            print(f"[{self.__class__.__name__}] Probe skipped: {probe_info.get('reason', 'unknown')}")

        fname = os.path.basename(input_path)
        print(f"[{self.__class__.__name__}] Decoding: {fname}")

        # Generate unique output path
        job_id = str(uuid.uuid4())[:8]
        output_wav = os.path.join(self.temp_dir, f"ingest_{job_id}.wav")

        # Build FFmpeg command
        cmd = [
            self.ffmpeg,
            "-y",                     # Overwrite
            "-hide_banner",           # Less noise
            "-loglevel", "error",     # Only errors
            "-i", input_path,         # Input
            "-vn",                    # Strip video
            "-acodec", TARGET_BIT_DEPTH,
            "-ar", str(TARGET_SAMPLE_RATE),
            "-ac", str(TARGET_CHANNELS),
            output_wav,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 min timeout for large files
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                raise RuntimeError(f"FFmpeg decode failed (code {result.returncode}): {stderr[:500]}")

            if not os.path.exists(output_wav):
                raise RuntimeError("FFmpeg produced no output file")

            out_size = os.path.getsize(output_wav)
            print(f"[{self.__class__.__name__}] ✓ Decode complete: {output_wav} ({out_size / 1024 / 1024:.1f} MB)")
            return output_wav

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"FFmpeg timed out after 600s decoding {fname}")
        except FileNotFoundError:
            raise RuntimeError(f"FFmpeg binary not found at: {self.ffmpeg}")

    # ── Export ───────────────────────────────────────────────────────────

    def finalize_export(self, processed_wav_path: str, original_input_path: str,
                        output_path: str, fmt: str = "WAV") -> bool:
        """
        Export the mastered audio to the final output path.
        - If source was video: mux treated audio back into the video container.
        - If FLAC: re-encode to 24-bit FLAC.
        - Otherwise: copy WAV directly.
        Returns True on success.
        """
        print(f"[{self.__class__.__name__}] Exporting ({fmt})...")

        ext_in = os.path.splitext(original_input_path)[1].lower()
        is_video = ext_in in {'.mp4', '.mov', '.mkv', '.avi', '.webm'}

        # ── Video → Mux audio back into original container ───────────
        if is_video:
            print(f"[{self.__class__.__name__}] Video source detected — muxing restored audio...")
            cmd = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", original_input_path,
                "-i", processed_wav_path,
                "-c:v", "copy",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                output_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600)
                print(f"[{self.__class__.__name__}] ✓ Video mux complete → {output_path}")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"[{self.__class__.__name__}] Video mux failed: {e}. Falling back to audio-only.")

        # ── FLAC export ──────────────────────────────────────────────
        if fmt.upper() == "FLAC":
            flac_path = os.path.splitext(output_path)[0] + ".flac"
            cmd = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", processed_wav_path,
                "-c:a", "flac",
                "-sample_fmt", "s32",  # 24-bit FLAC
                flac_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
                print(f"[{self.__class__.__name__}] ✓ FLAC export → {flac_path}")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                print(f"[{self.__class__.__name__}] FLAC encode failed, falling back to WAV.")

        # ── MP3 export ───────────────────────────────────────────────
        if fmt.upper() == "MP3":
            mp3_path = os.path.splitext(output_path)[0] + ".mp3"
            cmd = [
                self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", processed_wav_path,
                "-c:a", "libmp3lame",
                "-b:a", "320k",
                "-q:a", "0",
                mp3_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=300)
                print(f"[{self.__class__.__name__}] ✓ MP3 export (320kbps) → {mp3_path}")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                print(f"[{self.__class__.__name__}] MP3 encode failed, falling back to WAV.")

        # ── WAV fallback ─────────────────────────────────────────────
        shutil.copy2(processed_wav_path, output_path)
        print(f"[{self.__class__.__name__}] ✓ WAV export → {output_path}")
        return True
