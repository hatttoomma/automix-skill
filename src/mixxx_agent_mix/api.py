"""Synchronous API with source-time anchors and relative output automation."""
from .analysis import analyze_track
from .planner import make_plan
from .render import render


def analyze(track, *, mixxx_db=None, features=None):
    return analyze_track(track, mixxx_db=mixxx_db, features=features)


def plan(track_a, track_b, *, mode="auto", bars=8, strict=False, max_rate_change=0.08):
    """Compare styles by default and return an executable arrangement plan."""
    return make_plan(track_a, track_b, mode=mode, bars=bars, strict=strict, max_rate_change=max_rate_change)


def mix(track_a, track_b, output, *, mixxx_db=None, features_a=None, features_b=None,
        mode="auto", bars=8, strict=False, max_rate_change=0.08):
    """Decode -> analyze -> plan -> render -> verify -> MP3 + JSON report.

    An explicit mixxx_db requires both tracks to have usable native analysis.
    Omit it to use the labelled librosa fallback. Never overwrites outputs.
    Auto compares eligible transitions, layering, mashups and double drops.
    """
    a = analyze(track_a, mixxx_db=mixxx_db, features=features_a)
    b = analyze(track_b, mixxx_db=mixxx_db, features=features_b)
    transition = plan(a, b, mode=mode, bars=bars, strict=strict, max_rate_change=max_rate_change)
    return render(a, b, transition, output)
