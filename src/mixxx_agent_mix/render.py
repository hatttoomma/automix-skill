# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline render with a Python port of Mixxx's default constant-power fader.

Derived from EngineXfader::getXfadeGains (transform=1, curve=CONSTPWR,
reverse=false), Copyright (C) Mixxx Development Team, GPL-2.0-or-later.
Upstream commit: 3ebac449e7e5fe2a0186596657696e87ce8b0e56.
See THIRD_PARTY_NOTICES.md. Bass swap and offline pipeline are additions.
"""
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from scipy.signal import butter, sosfilt
import soundfile as sf

from .analysis import sha256
from .audio import SAMPLE_RATE, decode, run_ffmpeg


def crossfade_gains(t):
    """Mixxx default: linear gains then normalize gA²+gB² to 1."""
    t = np.clip(np.asarray(t), 0.0, 1.0)
    a, b = 1 - t, t
    norm = np.sqrt(a * a + b * b)
    return a / norm, b / norm


def _normalize(audio):
    rms = max(float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))), 1e-8)
    gain = float(np.clip(10 ** (-18 / 20) / rms, 0.5, 2.0))
    return audio * gain, 20 * np.log10(gain)


def _smoothstep(t, lo, hi):
    x = np.clip((t - lo) / (hi - lo), 0, 1)
    return x * x * (3 - 2 * x)


def render(a, b, transition, output):
    output = Path(output).expanduser().resolve()
    report_path = output.with_suffix(output.suffix + ".json")
    if output.suffix.lower() != ".mp3":
        raise ValueError("Output must have .mp3 extension")
    if output in (Path(a["path"]), Path(b["path"])):
        raise ValueError("Output must differ from the input tracks")
    if output.exists() or report_path.exists():
        raise FileExistsError("Output or report already exists; choose a new output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    audio_a, gain_a = _normalize(decode(a["path"]))
    audio_b, gain_b = _normalize(decode(b["path"], start=transition["entry_b_s"],
                                      rate=transition["rate_b"]))
    n = round(transition["overlap_s"] * SAMPLE_RATE)
    start = round(transition["exit_a_s"] * SAMPLE_RATE)
    if start + n > len(audio_a) or n > len(audio_b):
        raise ValueError("Decoded audio is shorter than transition plan")
    t = np.linspace(0, 1, n, dtype=np.float32)
    ga, gb = crossfade_gains(t)
    lowpass = butter(2, transition["bass_swap_hz"], fs=SAMPLE_RATE, output="sos")
    # Filter with A's preceding context so the low band is settled at fade start.
    low_a = sosfilt(lowpass, audio_a[:start + n], axis=0)[start:].astype(np.float32)
    low_b = sosfilt(lowpass, audio_b[:n], axis=0).astype(np.float32)
    swap = _smoothstep(t, 0.4, 0.6)[:, None]
    segment_a, segment_b = audio_a[start:start + n], audio_b[:n]
    blend = ga[:, None] * (segment_a - low_a + low_a * (1 - swap))
    blend += gb[:, None] * (segment_b - low_b + low_b * swap)
    audio = np.concatenate((audio_a[:start], blend, audio_b[n:]))
    del audio_a, audio_b, blend
    # 10 ms endpoint fades; never shorten or move the beat-aligned transition.
    edge = min(round(SAMPLE_RATE * 0.01), len(audio) // 2)
    audio[:edge] *= np.linspace(0, 1, edge)[:, None]
    audio[-edge:] *= np.linspace(1, 0, edge)[:, None]
    peak = float(np.max(np.abs(audio)))
    audio *= min(1.0, 10 ** (-1.5 / 20) / max(peak, 1e-8))
    with tempfile.TemporaryDirectory(prefix="agent-mix-", dir=output.parent) as directory:
        directory = Path(directory)
        wav, encoded = directory / "mix.wav", directory / "mix.mp3"
        # Check the decoded lossy result, since MP3 encoding can overshoot PCM peaks.
        for attempt in range(3):
            sf.write(wav, audio, SAMPLE_RATE, subtype="FLOAT")
            run_ffmpeg(["-y", "-i", str(wav), "-map_metadata", "-1", "-ar", str(SAMPLE_RATE),
                        "-ac", "2", "-codec:a", "libmp3lame", "-b:a", "320k", str(encoded)])
            checked = decode(encoded, max_seconds=1800)
            decoded_peak = float(np.max(np.abs(checked)))
            duration = len(checked) / SAMPLE_RATE
            if decoded_peak <= 10 ** (-1 / 20):
                break
            audio *= 10 ** (-1.2 / 20) / decoded_peak
        else:
            raise ValueError("Encoded output failed decoded sample-peak validation")
        if abs(duration - transition["expected_duration_s"]) > 0.15:
            raise ValueError("Encoded duration differs from transition plan by >150ms")
        result = {
            "schema_version": 1, "output": str(output), "report": str(report_path),
            "audio_sha256": sha256(encoded), "plan": transition,
            "analysis": {"a": a, "b": b},
            "validation": {"duration_s": duration, "sample_rate": SAMPLE_RATE, "channels": 2,
                "codec": "mp3", "decoded_sample_peak_dbfs": 20 * np.log10(max(decoded_peak, 1e-12)),
                "clipped_samples": int(np.count_nonzero(np.abs(checked) >= 1)),
                "gain_a_db": float(gain_a), "gain_b_db": float(gain_b),
                "peak_check": "decoded sample peak; not an intersample true-peak measurement"},
        }
        staged_report = directory / "report.json"
        staged_report.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                 encoding="utf-8")
        # Exclusive hard links avoid overwriting files even if another process races us.
        os.link(encoded, output)
        try:
            os.link(staged_report, report_path)
        except BaseException:
            output.unlink()
            raise
    return result
