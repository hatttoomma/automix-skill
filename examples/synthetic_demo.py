"""Generate original synthetic audio and exercise the public 2 MP3 -> 1 MP3 API.

Usage: python examples/synthetic_demo.py /tmp/agent-mix-demo
No audio assets are downloaded, and no Mixxx database is required.
"""
import argparse
from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf

from mixxx_agent_mix import mix
from mixxx_agent_mix.audio import SAMPLE_RATE, run_ffmpeg


def synthesize(output, bpm, seconds=40):
    sr = SAMPLE_RATE
    t = np.arange(round(seconds * sr)) / sr
    # C-major chord plus alternating kick accents; fixed tempo, instrumental.
    signal = sum(0.035 * np.sin(2 * np.pi * f * t) for f in (261.63, 329.63, 392.0))
    for index, beat in enumerate(np.arange(0, seconds, 60 / bpm)):
        start = round(beat * sr)
        n = min(round(0.13 * sr), len(t) - start)
        local = np.arange(n) / sr
        kick = np.sin(2 * np.pi * (75 * local - 100 * local**2)) * np.exp(-35 * local)
        click = np.sin(2 * np.pi * 1600 * local) * np.exp(-180 * local)
        signal[start:start + n] += (0.55 if index % 4 == 0 else 0.5) * kick + 0.15 * click
    # Musical envelope creates distinct entry/outro energy without changing tempo.
    signal *= 0.7 + 0.3 * np.sin(np.pi * t / seconds) ** 2
    stereo = np.column_stack((signal, signal * 0.98))
    with tempfile.TemporaryDirectory() as directory:
        wav = Path(directory) / "source.wav"
        sf.write(wav, stereo, sr)
        run_ffmpeg(["-y", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "192k", str(output)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    a, b = args.directory / "a.mp3", args.directory / "b.mp3"
    if a.exists() or b.exists():
        raise SystemExit("Choose an empty demo directory")
    synthesize(a, 120)
    synthesize(b, 124)
    result = mix(a, b, args.directory / "mixed.mp3")
    print(result["output"])
    print(result["report"])
