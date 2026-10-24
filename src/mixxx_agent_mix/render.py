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
from scipy.signal import butter, sosfiltfilt
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


def validate_automation(transition, sample_rate=SAMPLE_RATE):
    automation = transition.get("automation", {})
    if automation.get("gain_law") != "mixxx_constant_power_default":
        raise ValueError("Plan needs supported schema-2 gain/EQ automation")
    frames = automation.get("keyframes", [])
    if len(frames) < 2:
        raise ValueError("Automation requires at least two keyframes")
    times = np.array([f["time_s"] for f in frames], dtype=float)
    duration = transition["overlap_s"]
    if not np.isfinite(duration) or duration <= 0:
        raise ValueError("Automation duration must be positive and finite")
    if (not np.isfinite(times).all() or abs(times[0]) > 1e-9 or
            abs(times[-1] - duration) > 1e-6 or np.any(np.diff(times) <= 0)):
        raise ValueError("Automation times must increase from 0 to overlap duration")
    for field in ("mix", "level", "bass_a", "bass_b", "mid_a", "mid_b"):
        values = np.array([f[field] for f in frames], dtype=float)
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise ValueError(f"Automation {field} must be finite and in [0,1]")
    if any(f["bass_a"] + f["bass_b"] > 1.000001 for f in frames):
        raise ValueError("Automation cannot stack two full bass bands")
    if (frames[0]["mix"] != 0 or frames[-1]["mix"] != 1 or
            frames[0]["bass_a"] != 1 or frames[-1]["bass_b"] != 1 or
            frames[0]["mid_a"] != 1 or frames[-1]["mid_b"] != 1 or
            frames[0]["level"] != 1 or frames[-1]["level"] != 1):
        raise ValueError("Automation must join unmodified A and B at the endpoints")
    if not 0 < automation["bass_hz"] < automation["mid_high_hz"] < sample_rate / 2:
        raise ValueError("Invalid automation crossover frequencies")
    return automation


def render_overlap(context_a, segment_b, transition, *, sample_rate=SAMPLE_RATE):
    """Execute the complete overlap timeline, including sustained layers and EQ roles."""
    automation = validate_automation(transition, sample_rate)
    n = round(transition["overlap_s"] * sample_rate)
    if len(context_a) < n or len(segment_b) < n:
        raise ValueError("Audio is shorter than automation duration")
    frames = automation["keyframes"]
    times = np.arange(n) / sample_rate
    def envelope(field):
        return np.interp(times, [f["time_s"] for f in frames],
                         [f[field] for f in frames]).astype(np.float32)
    ga, gb = crossfade_gains(envelope("mix"))
    # Offline zero-phase filters avoid phase drift and give effective bass cuts.
    # The three complementary bands still sum exactly to the original source.
    def bands(audio):
        low = sosfiltfilt(butter(2, automation["bass_hz"], fs=sample_rate, output="sos"),
                      audio, axis=0).astype(np.float32)
        upper = sosfiltfilt(butter(2, automation["mid_high_hz"], fs=sample_rate, output="sos"),
                        audio, axis=0).astype(np.float32)
        return low, upper - low, audio - upper
    low_a, mid_a, high_a = [band[-n:] for band in bands(context_a)]
    low_b, mid_b, high_b = bands(segment_b[:n])
    a = low_a * envelope("bass_a")[:, None] + mid_a * envelope("mid_a")[:, None] + high_a
    b = low_b * envelope("bass_b")[:, None] + mid_b * envelope("mid_b")[:, None] + high_b
    return (a * ga[:, None] + b * gb[:, None]) * envelope("level")[:, None]


def render(a, b, transition, output):
    validate_automation(transition)
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
    # One second of filter context is sufficient for the 180 Hz two-pole filter.
    blend = render_overlap(audio_a[max(0, start - SAMPLE_RATE):start + n], audio_b[:n], transition)
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
            "schema_version": 2, "output": str(output), "report": str(report_path),
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
