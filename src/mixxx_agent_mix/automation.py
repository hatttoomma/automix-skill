"""Mode-specific, inspectable gain and frequency-band automation."""
import math


def make_automation(mode, duration, *, bass_owner="b", foreground=None, drop_offset=None, beat_s=0.5):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Arrangement duration must be positive and finite")
    if bass_owner not in ("a", "b"):
        raise ValueError("Bass owner must be a or b")
    if mode == "mashup" and foreground not in ("a", "b"):
        raise ValueError("Mashup needs a vocal foreground")
    if mode == "double_drop" and (drop_offset is None or not math.isfinite(drop_offset)
            or not math.isfinite(beat_s) or beat_s <= 0 or not beat_s < drop_offset < duration * 0.75):
        raise ValueError("Double drop needs a valid preroll and post-drop hold")
    def frame(time, mix, owner=None, level=1.0, bed_mid=1.0):
        owner = owner or bass_owner
        return {"time_s": float(time), "mix": float(mix), "level": float(level),
                "bass_a": float(owner == "a"), "bass_b": float(owner == "b"),
                "mid_a": bed_mid if foreground == "b" else 1.0,
                "mid_b": bed_mid if foreground == "a" else 1.0}

    start = frame(0, 0, "a")
    end = frame(duration, 1, "b")
    if mode == "transition":
        points = [start, frame(duration * 0.4, 0.4, "a"),
                  frame(duration * 0.6, 0.6, "b"), end]
    elif mode == "layering":
        points = [start, frame(duration * 0.25, 0.5),
                  frame(duration * 0.75, 0.5), end]
    elif mode == "mashup":
        position = 0.35 if foreground == "a" else 0.65
        points = [start, frame(duration * 0.125, position, bed_mid=0.45),
                  frame(duration * 0.875, position, bed_mid=0.45), end]
    elif mode == "double_drop":
        points = [start, frame(drop_offset - beat_s, 0.18, "a", level=0.85),
                  frame(drop_offset, 0.5), frame(duration * 0.75, 0.5), end]
    else:
        raise ValueError(f"Unknown mixing mode: {mode}")
    return {"gain_law": "mixxx_constant_power_default", "bass_hz": 180,
            "mid_high_hz": 3500, "keyframes": points}
