"""Stable synchronous Python API. All times are seconds in original source audio."""
from .analysis import analyze_track
from .planner import make_plan
from .render import render


def analyze(track, *, mixxx_db=None, features=None):
    return analyze_track(track, mixxx_db=mixxx_db, features=features)


def plan(track_a, track_b, *, bars=8, strict=False, max_rate_change=0.08):
    """Accept two analysis dictionaries and return an inspectable transition."""
    return make_plan(track_a, track_b, bars=bars, strict=strict, max_rate_change=max_rate_change)


def mix(track_a, track_b, output, *, mixxx_db=None, features_a=None, features_b=None,
        bars=8, strict=False, max_rate_change=0.08):
    """Decode -> analyze -> plan -> render -> verify -> MP3 + JSON report.

    An explicit mixxx_db requires both tracks to have usable native analysis.
    Omit it to use the labelled librosa fallback. Never overwrites outputs.
    """
    a = analyze(track_a, mixxx_db=mixxx_db, features=features_a)
    b = analyze(track_b, mixxx_db=mixxx_db, features=features_b)
    transition = plan(a, b, bars=bars, strict=strict, max_rate_change=max_rate_change)
    return render(a, b, transition, output)
