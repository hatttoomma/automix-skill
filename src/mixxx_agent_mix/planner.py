"""Compare musical arrangements, then emit executable gain/EQ automation."""
import numpy as np

from .automation import make_automation

MODES = ("transition", "layering", "mashup", "double_drop")


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
    expected = np.arange(count + 1) * duration / count
    error = float(np.max(np.abs((selected - start) / rate - expected)))
    return error if error <= 0.08 else None


def _starts(track, source_duration, *, outgoing=None):
    starts = [t for t in track["downbeats"] if t + source_duration + 0.05 < track["duration_s"]]
    if outgoing is True:
        starts = [t for t in starts if t >= track["duration_s"] * 0.55]
    elif outgoing is False:
        starts = [t for t in starts if t <= track["duration_s"] * 0.35
                  and t + source_duration + 2 < track["duration_s"]]
    if len(starts) > 64:
        # Retain section-adjacent anchors as well as evenly spaced whole-track anchors.
        sections = track["section_boundaries"]
        nearest = sorted(starts, key=lambda t: min([abs(t - s) for s in sections] or [0]))[:32]
        even = [starts[i] for i in np.linspace(0, len(starts) - 1, 32, dtype=int)]
        starts = sorted(set(nearest + even))
    return starts


def _windows(a, b, mode, duration, rate, pre_roll, strict):
    if mode != "double_drop":
        restriction = mode == "transition"
        for sa in _starts(a, duration, outgoing=True if restriction else None):
            for sb in _starts(b, duration * rate, outgoing=False if restriction else None):
                yield sa, sb, None
        return
    # Every pair must have two genuine supplied markers or two labelled estimates.
    for da in a.get("drops", []):
        for db in b.get("drops", []):
            if min(da["confidence"], db["confidence"]) < 0.65:
                continue
            if strict and (da["source"] != "external" or db["source"] != "external"):
                continue
            sa, sb = da["time_s"] - pre_roll, db["time_s"] - pre_roll * rate
            if (sa < 0 or sb < 0 or sa + duration + 0.05 >= a["duration_s"]
                    or sb + duration * rate + 0.05 >= b["duration_s"]):
                continue
            yield sa, sb, {"a": da, "b": db, "overlap_offset_s": pre_roll}


def _metrics(a, b, sa, sb, duration, rate):
    ea = _sample(a, "energy_curve", sa, duration)
    eb = _sample(b, "energy_curve", sb, duration * rate)
    ba = _sample(a, "low_frequency_energy", sa, duration)
    bb = _sample(b, "low_frequency_energy", sb, duration * rate)
    known = a["vocal_activity"] is not None and b["vocal_activity"] is not None
    va = _sample(a, "vocal_activity", sa, duration) if known else None
    vb = _sample(b, "vocal_activity", sb, duration * rate) if known else None
    return {"energy_gap_12db": abs(float(np.median(ea) - np.median(eb))) / 12,
            "bass_collision": float(np.mean(ba * bb)),
            "bass_a": float(np.mean(ba)), "bass_b": float(np.mean(bb)),
            "vocal_collision": float(np.mean(np.minimum(va, vb))) if known else None,
            "vocal_a": float(np.mean(va)) if known else None,
            "vocal_b": float(np.mean(vb)) if known else None}


def _score(a, b, mode, sa, sb, duration, metrics, alignment, drop):
    vocal = metrics["vocal_collision"]
    if vocal is not None and vocal > (0.15 if mode == "mashup" else 0.25):
        return None
    foreground = None
    if mode == "layering" and (metrics["energy_gap_12db"] > 0.5 or
                                (vocal is not None and vocal > 0.15)):
        return None
    if mode == "mashup":
        av, bv = metrics["vocal_a"], metrics["vocal_b"]
        if av is None or max(av, bv) < 0.5 or min(av, bv) > 0.15 or abs(av - bv) < 0.4:
            return None
        foreground = "a" if av > bv else "b"
    distance = sum(min([abs(t - s) for s in track["section_boundaries"]] or [8])
                   for track, t in ((a, sa), (b, sb)))
    trimming = (a["duration_s"] - sa - duration) / a["duration_s"] + sb / b["duration_s"]
    # These style priors express a creative preference after eligibility checks.
    # They are costs, not probabilities, and every mode uses the same common terms.
    prior = {"transition": 0.5, "layering": 0.3, "mashup": 0.2, "double_drop": 0.12}[mode]
    terms = {"style_prior": prior, "energy_balance": 0.4 * metrics["energy_gap_12db"],
        "bass_collision": 0.15 * metrics["bass_collision"],
        "section_distance": 0.15 * min(distance / 16, 2), "trimming": 0.1 * trimming,
        "beat_alignment": 0.15 * alignment / 0.08,
        "vocal_collision_or_uncertainty": 1.5 * vocal if vocal is not None else 0.12,
        "vocal_role_benefit": -0.1 * abs(metrics["vocal_a"] - metrics["vocal_b"]) if foreground else 0.0,
        "drop_uncertainty": 0.2 * (1 - min(drop["a"]["confidence"], drop["b"]["confidence"])) if drop else 0.0}
    return float(sum(terms.values())), foreground, terms


def make_plan(a, b, *, mode="auto", bars=8, strict=False, max_rate_change=0.08):
    if mode not in ("auto", *MODES):
        raise ValueError("mode must be auto, transition, layering, mashup or double_drop")
    if bars not in (4, 8, 16, 32):
        raise ValueError("bars must be 4, 8, 16 or 32 (4/4 meter)")
    if not 0 < max_rate_change <= 0.15:
        raise ValueError("max_rate_change must lie in (0, 0.15]")
    rate = a["bpm"] / b["bpm"]
    if not np.isfinite(rate) or abs(rate - 1) > max_rate_change:
        raise ValueError("BPM mismatch exceeds allowed tempo change; choose another pair")
    voice_known = a["vocal_activity"] is not None and b["vocal_activity"] is not None
    phase_known = all(t["sources"]["downbeats"] == "external" for t in (a, b))
    voice_verified = voice_known and all(t["sources"].get("vocal_activity") == "external" for t in (a, b))
    harmonic = compatible_keys(a["key"], b["key"])
    if strict and (not voice_verified or not phase_known or not harmonic):
        raise ValueError("Strict mode requires external downbeats/vocals and compatible keys")
    requested_bars = bars
    if not voice_known or not harmonic:
        bars = min(bars, 4)
    beats = bars * 4
    beat_s = 60 / a["bpm"]
    duration = beats * beat_s
    pre_roll = min(2, max(1, bars // 4)) * 4 * beat_s
    evaluation, winners = {}, []
    modes = MODES if mode == "auto" else (mode,)
    for technique in modes:
        reason = None
        if technique != "transition" and not harmonic:
            reason = "Creative layering requires compatible keys"
        elif technique == "mashup" and not voice_known:
            reason = "Mashup requires full-track vocal curves to assign vocal and bed roles"
        elif technique == "double_drop" and (not a.get("drops") or not b.get("drops")):
            reason = "Double drop requires drop markers or energy/bass-rise estimates in both tracks"
        candidates = []
        if reason is None:
            for sa, sb, drop in _windows(a, b, technique, duration, rate, pre_roll, strict):
                error_a = _aligned(a, sa, duration, beats, 1)
                error_b = _aligned(b, sb, duration, beats, rate)
                if error_a is None or error_b is None:
                    continue
                metrics = _metrics(a, b, sa, sb, duration, rate)
                alignment = max(error_a, error_b)
                rated = _score(a, b, technique, sa, sb, duration, metrics, alignment, drop)
                if rated is None:
                    continue
                score, foreground, terms = rated
                candidates.append({"mode": technique, "score": score, "exit_a_s": sa,
                    "entry_b_s": sb, "metrics": metrics, "alignment": alignment,
                    "foreground": foreground, "drop": drop, "cost_terms": terms})
        evaluation[technique] = {"eligible_candidates": len(candidates), "unavailable_reason": reason}
        if candidates:
            winners.append(min(candidates, key=lambda c: (c["score"], c["exit_a_s"], c["entry_b_s"])))
        elif reason is None:
            evaluation[technique]["unavailable_reason"] = (
                "No aligned low-vocal window meets this mode's duration, role or drop requirements")
    if not winners:
        detail = "; ".join(f"{m}: {e['unavailable_reason']}" for m, e in evaluation.items())
        raise ValueError("No safe aligned arrangement with a low-vocal window. " + detail)
    winners.sort(key=lambda c: (c["score"], MODES.index(c["mode"])))
    chosen = winners[0]
    technique, metrics = chosen["mode"], chosen["metrics"]
    sa, sb = chosen["exit_a_s"], chosen["entry_b_s"]
    foreground = chosen["foreground"]
    bass_owner = ("b" if foreground == "a" else "a") if foreground else (
        "a" if metrics["bass_a"] > metrics["bass_b"] else "b")
    warnings = []
    if not voice_known:
        warnings.append("Vocal activity unknown; use at most 4 bars and audition the overlap")
    if not phase_known:
        warnings.append("Downbeat phase estimated in 4/4; manually verify phrase alignment")
    if not harmonic:
        warnings.append("Key compatibility unconfirmed; use at most 4 bars without pitch shifting")
    if metrics["energy_gap_12db"] > 0.5:
        warnings.append("Transition energy differs by more than 6 dB before gain normalization")
    if technique == "mashup":
        warnings.append("Full-mix EQ mashup; no isolated vocals or stems are generated")
    drop = chosen["drop"]
    anchors = None
    if drop:
        anchors = {"drop_a_s": drop["a"]["time_s"], "drop_b_s": drop["b"]["time_s"],
                   "drop_output_s": sa + pre_roll, "overlap_offset_s": pre_roll,
                   "source_a": drop["a"]["source"], "source_b": drop["b"]["source"]}
        if any(drop[k]["source"] != "external" for k in ("a", "b")):
            warnings.append("Drop anchors are energy/bass-rise estimates; verify the musical drop by listening")
    reasons = {
        "transition": "Selected a phrase-aligned handoff with the lowest eligible arrangement cost",
        "layering": "Selected compatible, balanced windows for a sustained two-track layer",
        "mashup": f"Selected track {(foreground or '').upper()} as vocal foreground over the other track's bed",
        "double_drop": "Selected two drop anchors with synchronized buildup and a shared post-drop layer",
    }
    return {
        "schema_version": 2, "requested_mode": mode, "mode": technique,
        "target_bpm": a["bpm"], "rate_a": 1.0, "rate_b": rate,
        "requested_bars": requested_bars, "bars": bars, "meter": "4/4",
        "exit_a_s": sa, "entry_b_s": sb, "overlap_s": duration,
        "expected_duration_s": sa + (b["duration_s"] - sb) / rate,
        "crossfade": "mixxx_constant_power_default", "bass_swap_hz": 180,
        "pitch_shift_semitones": 0, "harmonic_compatible": harmonic,
        "roles": {"vocal_foreground": foreground,
                  "bass_owner": "handoff" if technique == "transition" else bass_owner},
        "anchors": anchors,
        "automation": make_automation(technique, duration, bass_owner=bass_owner,
            foreground=foreground, drop_offset=pre_roll if drop else None, beat_s=beat_s),
        "score": chosen["score"], "score_components": {**metrics, "cost_terms": chosen["cost_terms"],
            "max_beat_alignment_error_s": chosen["alignment"]}, "warnings": warnings,
        "selection": {"reason": reasons[technique], "evaluation": evaluation,
            "alternatives": [{k: c[k] for k in ("mode", "score", "exit_a_s", "entry_b_s")}
                             for c in winners]},
        "trim": "Keep A until arrangement end; discard A tail and B intro before entry",
    }
