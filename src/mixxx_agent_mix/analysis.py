"""Feature extraction. Estimated musical structure is explicitly labelled."""
import hashlib
import json
from pathlib import Path

import librosa
import numpy as np
from scipy.signal import find_peaks

from .audio import decode
from .mixxx_db import read_track

ANALYSIS_RATE = 22050
HOP = 512


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _key(chroma):
    # Krumhansl-style profile correlation: a heuristic, not calibrated probability.
    profiles = [np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]),
                np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])]
    vector = chroma.mean(axis=1)
    scores = [(float(np.corrcoef(vector, np.roll(profile, tonic))[0, 1]), tonic, mode)
              for profile, mode in zip(profiles, ("major", "minor")) for tonic in range(12)]
    scores = sorted((s for s in scores if np.isfinite(s[0])), reverse=True)
    if not scores:
        return None
    score, tonic, mode = scores[0]
    return {"tonic": tonic, "mode": mode, "confidence": max(0.0, score),
            "score_margin": score - scores[1][0]}


def _check_times(values, duration, name, minimum=1):
    if not isinstance(values, list) or len(values) < minimum:
        raise ValueError(f"{name} requires at least {minimum} timestamps")
    values = np.asarray(values, dtype=float)
    if (not np.isfinite(values).all() or np.any(values < 0) or
            np.any(values >= duration) or np.any(np.diff(values) <= 0)):
        raise ValueError(f"{name} must be finite, increasing seconds in [0, duration)")
    return values.tolist()


def estimate_drops(track):
    """Label strong downbeat energy/bass rises; scores are heuristics, not probabilities."""
    curve, bass = track["energy_curve"], track["low_frequency_energy"]
    times, energy = np.asarray(curve["times_s"]), np.asarray(curve["values"])
    low = np.interp(times, bass["times_s"], bass["values"])
    bar = 240 / track["bpm"]
    candidates = []
    for time in track["downbeats"]:
        if time < 2 * bar or time + bar >= track["duration_s"]:
            continue
        before = (times >= time - 2 * bar) & (times < time - 0.25)
        after = (times >= time) & (times < time + bar)
        if not np.any(before) or not np.any(after):
            continue
        rise = float(np.median(energy[after]) - np.median(energy[before]))
        bass_rise = float(np.mean(low[after]) - np.mean(low[before]))
        if rise >= 4.5 and bass_rise >= 0.08:
            candidates.append({"time_s": float(time),
                "confidence": float(min(0.95, 0.45 + rise / 30 + bass_rise * 0.5)),
                "source": "energy_bass_rise_estimate"})
    accepted = []
    for candidate in sorted(candidates, key=lambda c: -c["confidence"]):
        if all(abs(candidate["time_s"] - c["time_s"]) >= 4 * bar for c in accepted):
            accepted.append(candidate)
    return sorted(accepted, key=lambda c: c["time_s"])


def apply_features(analysis, feature_file):
    """Optional trusted detector/manual results, bound to the original encoded file."""
    with open(feature_file, encoding="utf-8") as handle:
        features = json.load(handle)
    if not isinstance(features, dict):
        raise ValueError("Feature sidecar must be a JSON object")
    if features.get("audio_sha256") != analysis["audio_sha256"]:
        raise ValueError("Feature sidecar audio_sha256 does not match input")
    allowed = {"audio_sha256", "downbeats", "vocal_activity", "section_boundaries", "drops"}
    if set(features) - allowed:
        raise ValueError("Unknown feature sidecar fields: " + str(set(features) - allowed))
    duration = analysis["duration_s"]
    if "downbeats" in features:
        downbeats = _check_times(features["downbeats"], duration, "downbeats", 2)
        beats = np.asarray(analysis["beat_timestamps"])
        if any(np.min(np.abs(beats - t)) > 0.08 for t in downbeats):
            raise ValueError("Downbeats must agree with beat timestamps within 80ms")
        # This MVP supports 4/4 only. A bar must cover approximately four beats.
        indices = [int(np.argmin(np.abs(beats - t))) for t in downbeats]
        if any(d != 4 for d in np.diff(indices)):
            raise ValueError("Provide consecutive 4/4 downbeats (four beats per bar)")
        analysis["downbeats"] = downbeats
        analysis["sources"]["downbeats"] = "external"
    if "section_boundaries" in features:
        analysis["section_boundaries"] = _check_times(
            features["section_boundaries"], duration, "section_boundaries")
        analysis["sources"]["section_boundaries"] = "external"
    if "vocal_activity" in features:
        curve = features["vocal_activity"]
        times = _check_times(curve["times_s"], duration, "vocal_activity.times_s", 2)
        values = np.asarray(curve["values"], dtype=float)
        if (values.ndim != 1 or len(times) != len(values) or
                not np.isfinite(values).all() or np.any((values < 0) | (values > 1))):
            raise ValueError("Vocal values must match times and lie in [0, 1]")
        if times[0] > 0.5 or times[-1] < duration - 1.5 or np.max(np.diff(times)) > 2.0:
            raise ValueError("Vocal curve must cover the entire track with <=2s gaps")
        analysis["vocal_activity"] = {"times_s": times, "values": values.tolist()}
        analysis["sources"]["vocal_activity"] = "external"
    if "drops" in features:
        drops = _check_times(features["drops"], duration, "drops", 0)
        downbeats = np.asarray(analysis["downbeats"])
        if any(np.min(np.abs(downbeats - t)) > 0.08 for t in drops):
            raise ValueError("Drops must agree with downbeats within 80ms")
        analysis["drops"] = [{"time_s": t, "confidence": 1.0, "source": "external"} for t in drops]
        analysis["sources"]["drops"] = "external"
    elif analysis["sources"].get("drops") != "external":
        analysis["drops"] = estimate_drops(analysis)
        analysis["sources"]["drops"] = "energy_bass_rise_estimate"
    return analysis


def analyze_track(path, *, mixxx_db=None, features=None):
    path = Path(path).expanduser().resolve(strict=True)
    stereo = decode(path, sample_rate=ANALYSIS_RATE)
    duration = len(stereo) / ANALYSIS_RATE
    # Quadratic stereo energy avoids false silence for opposite-phase channels.
    mono = stereo.mean(axis=1)
    if np.std(mono) < np.std(stereo) * 0.05:
        mono = stereo[:, 0]
    spectrum = librosa.stft(mono, n_fft=2048, hop_length=HOP)
    power = np.abs(spectrum) ** 2
    times = librosa.frames_to_time(np.arange(power.shape[1]), sr=ANALYSIS_RATE, hop_length=HOP)
    rms = librosa.feature.rms(S=np.abs(spectrum), frame_length=2048)[0]
    frequencies = librosa.fft_frequencies(sr=ANALYSIS_RATE, n_fft=2048)
    bass = np.sqrt(power[(frequencies >= 20) & (frequencies <= 180)].sum(axis=0))
    bass /= max(float(np.percentile(bass, 95)), 1e-10)
    chroma = librosa.feature.chroma_stft(S=power, sr=ANALYSIS_RATE, hop_length=HOP)
    native = read_track(mixxx_db, path, duration) if mixxx_db else None
    if native:
        bpm, beats = native["bpm"], np.array(native["beat_timestamps"])
    else:
        _, frames = librosa.beat.beat_track(y=mono, sr=ANALYSIS_RATE, hop_length=HOP, trim=False)
        beats = librosa.frames_to_time(frames, sr=ANALYSIS_RATE, hop_length=HOP)
        beats = beats[beats < duration]
        if len(beats) < 8:
            raise ValueError("No reliable beat sequence; analyze/correct the track in Mixxx")
        # Regress across all beats: median hop-quantized intervals can bias BPM.
        bpm = 60 / float(np.polyfit(np.arange(len(beats)), beats, 1)[0])
    # 4/4 phase from bass accents. This is NOT a trained downbeat detector.
    accent = np.interp(beats, times, bass)
    phase = int(np.argmax([np.mean(accent[p::4]) for p in range(4)]))
    downbeats = beats[phase::4]
    curve_times = np.arange(0, duration, 0.5)
    # Aggregate bins, never point-sample transients (which aliases kick energy).
    bins = []
    for t in curve_times:
        indices = np.flatnonzero((times >= t) & (times < min(t + 0.5, duration)))
        bins.append(indices if len(indices) else np.array([np.argmin(np.abs(times - t))]))
    energy = np.array([20 * np.log10(max(float(np.sqrt(np.mean(rms[ix] ** 2))), 1e-8))
                       for ix in bins])
    bass_curve = np.clip(np.array([np.mean(bass[ix]) for ix in bins]), 0, 1)
    # Sparse novelty peaks: boundaries only, no verse/chorus semantic labels.
    chroma_curve = np.stack([np.array([np.mean(row[ix]) for ix in bins]) for row in chroma])
    novelty = np.r_[0, np.linalg.norm(np.diff(chroma_curve, axis=1), axis=0)]
    novelty += np.abs(np.r_[0, np.diff(energy)]) / 12
    peaks, _ = find_peaks(novelty, distance=16, prominence=max(0.15, float(np.median(novelty))))
    boundaries = sorted({float(downbeats[np.argmin(np.abs(downbeats - curve_times[p]))])
                         for p in peaks})
    estimated_key = native["key"] if native and native["key"] else _key(chroma)
    analysis = {
        "schema_version": 2, "path": str(path), "audio_sha256": sha256(path),
        "duration_s": duration, "bpm": float(bpm), "beat_timestamps": beats.tolist(),
        "downbeats": downbeats.tolist(),
        "energy_curve": {"times_s": curve_times.tolist(), "values": energy.tolist(), "unit": "dBFS_rms"},
        "low_frequency_energy": {"times_s": curve_times.tolist(), "values": bass_curve.tolist(),
                                 "unit": "relative_20_180Hz_p95"},
        "key": estimated_key, "vocal_activity": None, "section_boundaries": boundaries,
        "sources": {"bpm": "mixxx" if native else "librosa",
                    "beat_timestamps": "mixxx" if native else "librosa",
                    "downbeats": "estimated_4_4_bass_phase", "energy_curve": "stft_rms",
                    "low_frequency_energy": "stft_20_180Hz",
                    "key": "mixxx" if native and native["key"] else "chroma_profile_estimate",
                    "vocal_activity": "unknown", "section_boundaries": "novelty_estimate"},
    }
    analysis["drops"] = estimate_drops(analysis)
    analysis["sources"]["drops"] = "energy_bass_rise_estimate"
    return apply_features(analysis, features) if features else analysis
