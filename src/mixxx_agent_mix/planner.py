"""Deterministic transition choice. Scores are preferences, not quality guarantees."""
import numpy as np


def compatible_keys(a, b):
    if a is None or b is None:
        return False
    ta, tb = a["tonic"], b["tonic"]
    if a["mode"] == b["mode"]:
        return (tb - ta) % 12 in (0, 5, 7)
    major, minor = (ta, tb) if a["mode"] == "major" else (tb, ta)
    return minor == (major + 9) % 12


def _sample(track, feature, start, duration, points=64):
    curve = track[feature]
    return np.interp(np.linspace(start, start + duration, points), curve["times_s"], curve["values"])


def _aligned(track, start, duration, count, rate):
    beats = np.asarray(track["beat_timestamps"])
    index = int(np.argmin(np.abs(beats - start)))
    selected = beats[index:index + count + 1]
    if len(selected) != count + 1:
        return None
    relative = (selected - start) / rate
    expected = np.arange(count + 1) * duration / count
    error = float(np.max(np.abs(relative - expected)))
    return error if error <= 0.08 else None


def make_plan(a, b, *, bars=8, strict=False, max_rate_change=0.08):
    if bars not in (4, 8, 16, 32):
        raise ValueError("bars must be 4, 8, 16 or 32 (4/4 meter)")
    if not 0 < max_rate_change <= 0.15:
        raise ValueError("max_rate_change must lie in (0, 0.15]")
    rate = a["bpm"] / b["bpm"]
    if abs(rate - 1) > max_rate_change:
        raise ValueError("BPM mismatch exceeds allowed tempo change; choose another pair")
    warnings = []
    voice_known = a["vocal_activity"] is not None and b["vocal_activity"] is not None
    phase_known = all(t["sources"]["downbeats"] == "external" for t in (a, b))
    harmonic = compatible_keys(a["key"], b["key"])
    if not voice_known:
        warnings.append("Vocal activity unknown; use at most 4 bars and audition the overlap")
    if not phase_known:
        warnings.append("Downbeat phase estimated in 4/4; manually verify phrase alignment")
    if not harmonic:
        warnings.append("Key compatibility unconfirmed; use at most 4 bars without pitch shifting")
    if strict and (not voice_known or not phase_known or not harmonic):
        raise ValueError("Strict mode requires external downbeats/vocals and compatible keys")
    requested_bars = bars
    if not voice_known or not harmonic:
        bars = min(bars, 4)
    beat_count = bars * 4
    duration = beat_count * 60 / a["bpm"]
    # Favor outgoing final 45% and incoming first 35%; preserve at least 2s after fade.
    exits = [t for t in a["downbeats"] if t >= a["duration_s"] * 0.55
             and t + duration <= a["duration_s"] - 0.05]
    entries = [t for t in b["downbeats"] if t <= b["duration_s"] * 0.35
               and t + duration * rate + 2 < b["duration_s"]]
    candidates = []
    for exit_a in exits:
        error_a = _aligned(a, exit_a, duration, beat_count, 1)
        if error_a is None:
            continue
        for entry_b in entries:
            error_b = _aligned(b, entry_b, duration, beat_count, rate)
            if error_b is None:
                continue
            energy_a = _sample(a, "energy_curve", exit_a, duration)
            energy_b = _sample(b, "energy_curve", entry_b, duration * rate)
            energy_gap = abs(float(np.median(energy_a) - np.median(energy_b))) / 12
            bass_a = _sample(a, "low_frequency_energy", exit_a, duration)
            bass_b = _sample(b, "low_frequency_energy", entry_b, duration * rate)
            bass_collision = float(np.mean(bass_a * bass_b))
            vocal_collision = 0.0
            if voice_known:
                va = _sample(a, "vocal_activity", exit_a, duration)
                vb = _sample(b, "vocal_activity", entry_b, duration * rate)
                vocal_collision = float(np.mean(np.minimum(va, vb)))
                if vocal_collision > 0.25:
                    continue
            # Distance to a detected section boundary encourages phrase-level entry.
            section_distance = sum(min([abs(t - s) for s in track["section_boundaries"]] or [8])
                                   for track, t in ((a, exit_a), (b, entry_b)))
            retention = (a["duration_s"] - exit_a - duration) / a["duration_s"]
            retention += entry_b / b["duration_s"]
            score = (4 * vocal_collision + energy_gap + 0.5 * bass_collision
                     + min(section_distance / 16, 2) * 0.5 + retention)
            candidates.append((score, exit_a, entry_b, energy_gap, vocal_collision,
                               bass_collision, max(error_a, error_b)))
    if not candidates:
        raise ValueError("No safe aligned transition: need stable 4/4 beats, enough audio and a low-vocal window")
    score, exit_a, entry_b, gap, voice, bass, alignment = min(candidates)
    if gap > 0.5:
        warnings.append("Transition energy differs by more than 6 dB before gain normalization")
    return {
        "schema_version": 1, "target_bpm": a["bpm"], "rate_a": 1.0, "rate_b": rate,
        "requested_bars": requested_bars, "bars": bars, "meter": "4/4",
        "exit_a_s": exit_a, "entry_b_s": entry_b, "overlap_s": duration,
        "expected_duration_s": exit_a + (b["duration_s"] - entry_b) / rate,
        "crossfade": "mixxx_constant_power_default", "bass_swap_hz": 180,
        "pitch_shift_semitones": 0, "harmonic_compatible": harmonic,
        "score": float(score), "score_components": {"energy_gap_12db": gap,
          "vocal_collision": voice if voice_known else None, "bass_collision": bass,
          "max_beat_alignment_error_s": alignment}, "warnings": warnings,
        "trim": "Keep A until fade end; discard A tail and B intro before entry",
    }
