"""Local decode/encode. No network services or shell-interpolated filenames."""
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 44100
MAX_SECONDS = 900


def ffmpeg():
    binary = os.environ.get("MIXXX_AGENT_FFMPEG") or shutil.which("ffmpeg")
    if not binary:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
    return binary


def run_ffmpeg(args):
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        raise ValueError("FFmpeg: " + result.stderr.decode(errors="replace")[-2000:])
    return result.stdout


def decode(path, *, sample_rate=SAMPLE_RATE, start=0.0, rate=1.0, max_seconds=MAX_SECONDS):
    path = Path(path).expanduser().resolve(strict=True)
    filters = f"atrim=start={start:.9f},asetpts=PTS-STARTPTS"
    if abs(rate - 1.0) > 1e-9:
        filters += f",atempo={rate:.9f}"
    # Decode one extra second to detect excessive input length instead of truncating silently.
    raw = run_ffmpeg([
        "-i", str(path), "-map", "0:a:0", "-vn", "-af", filters,
        "-t", str(max_seconds + 1), "-ar", str(sample_rate), "-ac", "2",
        "-f", "f32le", "pipe:1",
    ])
    audio = np.frombuffer(raw, dtype="<f4").reshape(-1, 2).copy()
    if len(audio) > max_seconds * sample_rate:
        raise ValueError(f"Track exceeds {max_seconds}s in rendered time; split it first")
    if len(audio) < sample_rate * 2 or not np.isfinite(audio).all():
        raise ValueError("Need at least 2 seconds of finite decoded audio")
    if np.max(np.abs(audio)) < 1e-6:
        raise ValueError("Track is silent")
    return audio
