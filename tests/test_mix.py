import copy
import json
from pathlib import Path

import numpy as np
import pytest

from mixxx_agent_mix import analyze, mix, plan
from mixxx_agent_mix.analysis import apply_features, sha256
from mixxx_agent_mix.audio import decode
from mixxx_agent_mix.cli import main
from mixxx_agent_mix.mixxx_db import decode_beats, read_track
from mixxx_agent_mix.render import crossfade_gains
from conftest import grid, varint


def test_mixxx_native_frames_and_negative_anchor():
    bpm, beats = decode_beats(grid(120, -22050), "BeatGrid-2.0", 44100, 10)
    assert bpm == 120
    assert beats[:4] == [0, 0.5, 1, 1.5]  # frames, not interleaved stereo samples


def test_mixxx_variable_map():
    frames = [0, 22050, 44100, 66300, 88350, 110400, 132450, 154500, 176550]
    blob = b"".join(b"\x0a" + varint(len(b"\x08" + varint(x))) + b"\x08" + varint(x) for x in frames)
    _, beats = decode_beats(blob, "BeatMap-1.0", 44100, 5)
    assert np.allclose(beats, np.array(frames) / 44100)


@pytest.mark.parametrize("blob,version", [(b"\x0a\x10", "BeatGrid-2.0"),
    (grid(120), "BeatGrid-1.0"), (b"\x00", "BeatMap-1.0"), (grid(float("nan")), "BeatGrid-2.0")])
def test_mixxx_invalid_formats_fail(blob, version):
    with pytest.raises(ValueError):
        decode_beats(blob, version, 44100, 10)


def test_mixxx_read_only_and_explicit_missing_track(tracks):
    a, _, db = tracks
    before = sha256(db)
    result = read_track(db, a, 40)
    assert result["key"]["tonic"] == 0
    assert result["key"]["mode"] == "major"
    assert sha256(db) == before
    with pytest.raises(ValueError, match="missing"):
        read_track(db, a.with_name("missing.mp3"), 40)


def test_mixxx_fader_endpoints_and_constant_power():
    a, b = crossfade_gains(np.linspace(0, 1, 101))
    assert (a[0], b[0], a[-1], b[-1]) == (1, 0, 0, 1)
    assert np.allclose(a * a + b * b, 1)
    assert a[50] == pytest.approx(2 ** -0.5)


@pytest.fixture(scope="module")
def analyses(tracks):
    a, b, db = tracks
    return analyze(a, mixxx_db=db), analyze(b, mixxx_db=db)


def test_analysis_has_all_requested_features(analyses):
    a, _ = analyses
    assert set(("bpm", "beat_timestamps", "downbeats", "energy_curve", "low_frequency_energy",
                "key", "vocal_activity", "section_boundaries")) <= set(a)
    assert a["sources"]["bpm"] == "mixxx"
    assert a["vocal_activity"] is None
    assert "estimated" in a["sources"]["downbeats"]


def test_plan_alignment_and_conservative_fallback(analyses):
    a, b = analyses
    p = plan(a, b, bars=16)
    assert p["bars"] == 4 and p["requested_bars"] == 16
    assert p["rate_b"] == pytest.approx(120 / 124)
    assert p["exit_a_s"] in a["downbeats"] and p["entry_b_s"] in b["downbeats"]
    assert p["score_components"]["vocal_collision"] is None
    assert p["score_components"]["max_beat_alignment_error_s"] < 0.001
    assert p["warnings"]
    with pytest.raises(ValueError, match="Strict"):
        plan(a, b, strict=True)
    too_fast = copy.deepcopy(b)
    too_fast["bpm"] = 150
    with pytest.raises(ValueError, match="BPM"):
        plan(a, too_fast)


def test_variable_tempo_drift_rejected(analyses):
    a, b = copy.deepcopy(analyses)
    b["beat_timestamps"] = [t + (i % 2) * 0.2 for i, t in enumerate(b["beat_timestamps"])]
    with pytest.raises(ValueError, match="No safe aligned"):
        plan(a, b)


def test_vocal_overlap_rejected(analyses):
    a, b = copy.deepcopy(analyses)
    for track in (a, b):
        track["sources"]["downbeats"] = "external"
        track["vocal_activity"] = {"times_s": [0, 39.5], "values": [1, 1]}
    with pytest.raises(ValueError, match="low-vocal"):
        plan(a, b, strict=True)


def test_sidecar_hash_and_sparse_voice_rejected(analyses, tmp_path):
    a = copy.deepcopy(analyses[0])
    sidecar = tmp_path / "features.json"
    sidecar.write_text(json.dumps({"audio_sha256": "wrong"}))
    with pytest.raises(ValueError, match="sha256"):
        apply_features(a, sidecar)
    sidecar.write_text(json.dumps({"audio_sha256": a["audio_sha256"],
        "vocal_activity": {"times_s": [0, 39.5], "values": [0, 0]}}))
    with pytest.raises(ValueError, match="cover"):
        apply_features(a, sidecar)


def test_strict_plan_accepts_verified_features(analyses, tmp_path):
    a, b = copy.deepcopy(analyses)
    for i, track in enumerate((a, b)):
        times = np.arange(0, track["duration_s"], 0.5).tolist()
        sidecar = tmp_path / f"features-{i}.json"
        sidecar.write_text(json.dumps({"audio_sha256": track["audio_sha256"],
            "downbeats": track["beat_timestamps"][::4],
            "vocal_activity": {"times_s": times, "values": [0] * len(times)}}))
        apply_features(track, sidecar)
    p = plan(a, b, bars=8, strict=True)
    assert p["bars"] == 8
    assert not p["warnings"]


@pytest.mark.parametrize("native", [True, False])
def test_real_two_mp3_to_one_mp3(tracks, tmp_path, native):
    a, b, db = tracks
    out = tmp_path / "mixed.mp3"
    result = mix(a, b, out, mixxx_db=db if native else None)
    assert out.stat().st_size > 50000
    assert Path(result["report"]).is_file()
    audio = decode(out, max_seconds=1800)
    assert audio.shape[1] == 2
    assert result["validation"]["clipped_samples"] == 0
    assert result["validation"]["decoded_sample_peak_dbfs"] <= -1
    assert result["audio_sha256"] == sha256(out)
    assert abs(len(audio) / 44100 - result["plan"]["expected_duration_s"]) < 0.15
    assert json.loads(Path(result["report"]).read_text())["output"] == str(out)
    original = sha256(out)
    with pytest.raises(FileExistsError):
        mix(a, b, out, mixxx_db=db if native else None)
    assert sha256(out) == original


def test_cli_error_is_machine_readable(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "missing.mp3")]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_atempo_preserves_pitch_and_changes_duration(tracks):
    _, b, _ = tracks
    original = decode(b)
    faster = decode(b, rate=1.06)
    assert abs(len(faster) / len(original) - 1 / 1.06) < 0.003
    def chord_tones(audio):
        # Inspect a stationary chord band, away from kick fundamentals.
        segment = audio[5 * 44100:9 * 44100, 0]
        spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
        frequencies = np.fft.rfftfreq(len(segment), 1 / 44100)
        peaks = []
        for lo, hi in [(240, 290), (300, 360), (370, 430)]:
            band = (frequencies > lo) & (frequencies < hi)
            peaks.append(frequencies[band][np.argmax(spectrum[band])])
        return np.array(peaks)
    assert np.max(np.abs(chord_tones(original) - chord_tones(faster))) < 1
