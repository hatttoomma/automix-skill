import copy
import json
from pathlib import Path

import numpy as np
import pytest

from mixxx_agent_mix import analyze, mix, plan
from mixxx_agent_mix.analysis import apply_features, estimate_drops
from mixxx_agent_mix.automation import make_automation
from mixxx_agent_mix.cli import main
from mixxx_agent_mix.render import render_overlap, validate_automation


def feature_track(*, voice=0.0, energy=-18.0, bpm=120.0, duration=80.0):
    times = np.arange(0, duration, 0.5).tolist()
    beats = np.arange(0, duration, 60 / bpm).tolist()
    return {"audio_sha256": "fixture", "duration_s": duration, "bpm": bpm,
        "beat_timestamps": beats, "downbeats": beats[::4],
        "energy_curve": {"times_s": times, "values": [energy] * len(times)},
        "low_frequency_energy": {"times_s": times, "values": [0.4] * len(times)},
        "vocal_activity": {"times_s": times, "values": [voice] * len(times)} if voice is not None else None,
        "section_boundaries": [0.0, 16.0, 32.0, 48.0, 64.0],
        "key": {"tonic": 0, "mode": "major"}, "drops": [],
        "sources": {"downbeats": "external", "drops": "external",
                    "vocal_activity": "external" if voice is not None else "unknown"}}


def drop(time, *, source="external", confidence=1.0):
    return {"time_s": time, "source": source, "confidence": confidence}


@pytest.mark.parametrize("mode", ["transition", "layering", "mashup", "double_drop"])
def test_auto_can_choose_each_mode(mode):
    a, b = feature_track(), feature_track()
    if mode == "transition":
        b["key"] = {"tonic": 1, "mode": "major"}
    elif mode == "mashup":
        a = feature_track(voice=0.9)
    elif mode == "double_drop":
        a["drops"], b["drops"] = [drop(32)], [drop(48)]
    decision = plan(a, b)
    assert decision["requested_mode"] == "auto"
    assert decision["mode"] == mode
    assert set(decision["selection"]["evaluation"]) == {"transition", "layering", "mashup", "double_drop"}
    alternatives = decision["selection"]["alternatives"]
    assert decision["score"] == min(c["score"] for c in alternatives)
    assert decision["score"] == pytest.approx(sum(decision["score_components"]["cost_terms"].values()))
    validate_automation(decision)


def test_creative_windows_are_not_limited_to_outro_and_intro():
    a, b = feature_track(), feature_track()
    a["drops"], b["drops"] = [drop(32)], [drop(48)]
    decision = plan(a, b, mode="double_drop", strict=True)
    assert decision["exit_a_s"] < a["duration_s"] * 0.55
    assert decision["entry_b_s"] > b["duration_s"] * 0.35


def test_double_drop_alignment_accounts_for_b_tempo_change():
    a, b = feature_track(), feature_track(bpm=124)
    a["drops"], b["drops"] = [drop(32)], [drop(16 * 240 / 124)]
    decision = plan(a, b, mode="double_drop")
    anchor = decision["anchors"]
    event_a = decision["exit_a_s"] + (anchor["drop_a_s"] - decision["exit_a_s"])
    event_b = decision["exit_a_s"] + (anchor["drop_b_s"] - decision["entry_b_s"]) / decision["rate_b"]
    assert event_a == pytest.approx(event_b, abs=1e-8)
    assert event_a == pytest.approx(anchor["drop_output_s"])
    frames = decision["automation"]["keyframes"]
    assert any(f["time_s"] == anchor["overlap_offset_s"] and f["mix"] == 0.5 for f in frames)


@pytest.mark.parametrize("foreground", ["a", "b"])
def test_mashup_assigns_vocal_and_bass_roles(foreground):
    a = feature_track(voice=0.9 if foreground == "a" else 0.0)
    b = feature_track(voice=0.9 if foreground == "b" else 0.0)
    decision = plan(a, b, mode="mashup", strict=True)
    assert decision["roles"]["vocal_foreground"] == foreground
    assert decision["roles"]["bass_owner"] != foreground
    middle = decision["automation"]["keyframes"][1]
    assert middle["mid_" + foreground] == 1.0
    assert middle["mid_" + ("b" if foreground == "a" else "a")] < 0.5
    assert any("no isolated vocals" in warning for warning in decision["warnings"])


def test_explicit_modes_do_not_silently_fallback():
    a, b = feature_track(voice=None), feature_track()
    with pytest.raises(ValueError, match="vocal curves"):
        plan(a, b, mode="mashup")
    with pytest.raises(ValueError, match="drop markers"):
        plan(a, b, mode="double_drop")
    auto = plan(a, b)
    assert auto["mode"] in ("transition", "layering")
    assert auto["bars"] == 4
    assert auto["score_components"]["vocal_collision"] is None
    with pytest.raises(ValueError, match="mode must"):
        plan(a, b, mode="invented")


def test_generic_boundaries_do_not_count_as_drops():
    a, b = feature_track(), feature_track()
    assert estimate_drops(a) == []
    assert plan(a, b)["mode"] != "double_drop"


def test_energy_and_bass_rise_estimates_are_labelled():
    a = feature_track()
    times = np.array(a["energy_curve"]["times_s"])
    a["energy_curve"]["values"] = np.where(times < 32, -30, -15).tolist()
    a["low_frequency_energy"]["values"] = np.where(times < 32, 0.1, 0.8).tolist()
    estimates = estimate_drops(a)
    assert estimates and estimates[0]["time_s"] == 32
    assert estimates[0]["source"] == "energy_bass_rise_estimate"
    assert estimates[0]["confidence"] >= 0.65
    a["drops"] = estimates
    b = copy.deepcopy(a)
    decision = plan(a, b, mode="double_drop")
    assert any("Drop anchors" in warning for warning in decision["warnings"])
    with pytest.raises(ValueError, match="drop requirements"):
        plan(a, b, mode="double_drop", strict=True)


def test_low_confidence_or_out_of_bounds_drops_are_rejected():
    a, b = feature_track(), feature_track()
    for marker in [drop(32, confidence=0.4), drop(0), drop(78)]:
        a["drops"] = b["drops"] = [marker]
        with pytest.raises(ValueError, match="No safe aligned"):
            plan(a, b, mode="double_drop")


def test_external_drop_sidecar_checks_grid_and_allows_no_drops(tmp_path):
    a = feature_track()
    file = tmp_path / "features.json"
    for markers in ([32], []):
        file.write_text(json.dumps({"audio_sha256": "fixture", "drops": markers}))
        result = apply_features(copy.deepcopy(a), file)
        assert result["sources"]["drops"] == "external"
        assert len(result["drops"]) == len(markers)
    file.write_text(json.dumps({"audio_sha256": "fixture", "drops": [33]}))
    with pytest.raises(ValueError, match="downbeats"):
        apply_features(a, file)


def _tone_amplitude(audio, frequency, sample_rate):
    time = np.arange(len(audio)) / sample_rate
    return abs(np.dot(audio, np.exp(-2j * np.pi * frequency * time))) * 2 / len(audio)


def test_renderer_sustains_layer_and_suppresses_nonowner_bass():
    sr, duration = 8000, 8
    time = np.arange(sr * duration) / sr
    a = 0.1 * (np.sin(2 * np.pi * 1000 * time) + np.sin(2 * np.pi * 80 * time))
    b = 0.1 * (np.sin(2 * np.pi * 1300 * time) + np.sin(2 * np.pi * 110 * time))
    decision = {"overlap_s": duration, "automation": make_automation("layering", duration, bass_owner="b")}
    rendered = render_overlap(np.column_stack((a, a)), np.column_stack((b, b)), decision, sample_rate=sr)
    early, late = rendered[3 * sr:4 * sr, 0], rendered[5 * sr:6 * sr, 0]
    for frequency in (1000, 1300):
        assert _tone_amplitude(early, frequency, sr) > 0.06
        assert _tone_amplitude(early, frequency, sr) == pytest.approx(
            _tone_amplitude(late, frequency, sr), rel=0.02)
    assert _tone_amplitude(early, 80, sr) < _tone_amplitude(early, 110, sr) * 0.15
    # A conventional crossfade has no fixed-gain plateau at those times.
    decision["automation"] = make_automation("transition", duration)
    faded = render_overlap(np.column_stack((a, a)), np.column_stack((b, b)), decision, sample_rate=sr)
    assert _tone_amplitude(faded[3 * sr:4 * sr, 0], 1000, sr) > 1.3 * _tone_amplitude(
        faded[5 * sr:6 * sr, 0], 1000, sr)


def test_mashup_renderer_attenuates_bed_midrange():
    sr, duration = 8000, 8
    time = np.arange(sr * duration) / sr
    a, b = [0.1 * np.sin(2 * np.pi * f * time) for f in (1000, 1300)]
    decision = {"overlap_s": duration,
        "automation": make_automation("mashup", duration, bass_owner="b", foreground="a")}
    output = render_overlap(np.column_stack((a, a)), np.column_stack((b, b)), decision, sample_rate=sr)
    middle = output[3 * sr:5 * sr, 0]
    assert _tone_amplitude(middle, 1000, sr) > 3 * _tone_amplitude(middle, 1300, sr)


def test_renderer_rejects_invalid_automation():
    decision = {"overlap_s": 8, "automation": make_automation("layering", 8)}
    decision["automation"]["keyframes"][1]["time_s"] = 0
    with pytest.raises(ValueError, match="increase"):
        validate_automation(decision)
    decision["automation"] = make_automation("layering", 8)
    decision["automation"]["keyframes"][1]["bass_a"] = 1
    with pytest.raises(ValueError, match="bass bands"):
        validate_automation(decision)


@pytest.mark.parametrize("mode", ["transition", "layering", "mashup", "double_drop"])
def test_each_mode_renders_real_mp3(tracks, tmp_path, mode):
    a_path, b_path, database = tracks
    sidecars = []
    for index, path in enumerate((a_path, b_path)):
        analysis = analyze(path, mixxx_db=database)
        times = np.arange(0, analysis["duration_s"], 0.5).tolist()
        payload = {"audio_sha256": analysis["audio_sha256"],
            "downbeats": analysis["beat_timestamps"][::4],
            "vocal_activity": {"times_s": times,
                "values": [0.9 if mode == "mashup" and index == 0 else 0.0] * len(times)},
            "drops": [analysis["beat_timestamps"][32]] if mode == "double_drop" else []}
        file = tmp_path / f"{index}.features.json"
        file.write_text(json.dumps(payload))
        sidecars.append(file)
    result = mix(a_path, b_path, tmp_path / f"{mode}.mp3", mode=mode, mixxx_db=database,
        features_a=sidecars[0], features_b=sidecars[1], strict=True)
    assert result["plan"]["mode"] == mode
    assert result["validation"]["clipped_samples"] == 0
    assert result["validation"]["decoded_sample_peak_dbfs"] <= -1
    assert abs(result["validation"]["duration_s"] - result["plan"]["expected_duration_s"]) < 0.15
    assert Path(result["output"]).stat().st_size > 50000
    report = json.loads(Path(result["report"]).read_text())
    assert report["plan"]["automation"] == result["plan"]["automation"]


def test_cli_passes_explicit_mode(tracks, capsys):
    a, b, database = tracks
    assert main(["plan", str(a), str(b), "--mode", "layering", "--mixxx-db", str(database)]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["mode"] == "layering"
    assert decision["requested_mode"] == "layering"
