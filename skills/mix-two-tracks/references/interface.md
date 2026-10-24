# Interface and JSON fields

## CLI

```bash
agent-mix analyze A.mp3 [--mixxx-db DB] [--features A.features.json]
agent-mix plan A.mp3 B.mp3 [--mode auto] [--mixxx-db DB] [--features-a FILE] [--features-b FILE] [--bars 8] [--strict]
agent-mix mix A.mp3 B.mp3 -o OUT.mp3 [the same planning options]
```

Modes are `auto` (default), `transition`, `layering`, `mashup`, and `double_drop`. Planning and mixing also accept `--max-rate-change 0.08`. Explicit modes fail if their requirements are unmet; auto can select another eligible mode. See [mixing-modes.md](mixing-modes.md) for eligibility and scoring.

Success returns exit code 0 and JSON on stdout. Handled input, planning, or output errors return exit code 2 and `{"error":"..."}` on stderr. Planning does not render audio. Mixing writes an MP3 and an adjacent sidecar; existing output or report files cause failure.

## Analysis object

| Field | Meaning |
|---|---|
| `schema_version` | 2. |
| `path`, `audio_sha256` | Local input path and SHA-256 of the original encoded file. |
| `duration_s`, `bpm` | Decoded duration and estimated or native Mixxx BPM. |
| `beat_timestamps`, `downbeats` | Increasing timestamps in original source-audio seconds. |
| `energy_curve` | `times_s`, `values`, and `unit=dBFS_rms`; approximately 0.5-second bins. |
| `low_frequency_energy` | The same curve structure; relative 20-180 Hz energy normalized to each track's P95, in 0-1. |
| `key` | `tonic` from C=0 to B=11 and `mode=major/minor`; `confidence` is correlation or null, not a calibrated probability. The object may be null. |
| `vocal_activity` | Null or `{times_s, values}` with externally supplied 0-1 activity. |
| `section_boundaries` | Candidate boundary times, without semantic verse/chorus labels. |
| `drops` | List of `{time_s, confidence, source}`. Source is `external` or `energy_bass_rise_estimate`. An empty list means no usable markers. |
| `sources` | Per-feature provenance including mixxx, librosa, estimated, external, and unknown. |

The timeline excludes MP3 encoder-delay metadata; FFmpeg handles gapless decoding. Convert native Mixxx positions with `frame_position / native_samplerate`, without dividing by channel count or substituting the analysis sample rate.

Drop confidence is a heuristic score. External markers receive 1.0 by caller assertion, which does not independently establish accuracy. Estimates are recalculated when external downbeats change unless external drops are supplied.

## Plan object

Plans use schema version 2 and include:

- `requested_mode`, `mode`: Requested and selected styles.
- `target_bpm`, `rate_a=1`, `rate_b`: `rate_b=target_bpm/BPM_B`; values above 1 speed B up while retaining pitch.
- `exit_a_s`, `entry_b_s`: Start of the arrangement in each original source, even when A continues playing throughout a layer.
- `overlap_s`, `bars`, `requested_bars`: Rendered arrangement duration and effective/requested total bar counts. The count includes entry and exit ramps, plus any buildup and hold.
- `expected_duration_s`: `exit_a_s + (duration_B-entry_b_s)/rate_b`.
- `roles`: `vocal_foreground` is `a`, `b`, or null; `bass_owner` is `a` or `b` during a sustained region, or `handoff` for a transition.
- `anchors`: Null except for double drop. Contains `drop_a_s`, `drop_b_s`, `drop_output_s`, `overlap_offset_s`, `source_a`, and `source_b`.
- `automation`: Gain law, crossover frequencies, and executable keyframes.
- `score`, `score_components`: Cost, musical metrics, alignment error, and weighted cost terms. Lower is preferred; scores are not quality probabilities.
- `selection`: Human-readable reason, the best ranked alternative for each eligible mode, and evaluation counts/unavailable reasons. Explicit requests evaluate only the requested mode.
- `warnings`, `trim`: Uncertainty and source-trimming disclosure.

B's original overlap window lasts `overlap_s * rate_b`. Double-drop anchors share output time `exit_a_s + (drop_B-entry_b_s)/rate_b`, equal to the A drop's output time.

### Automation

`automation` contains `gain_law=mixxx_constant_power_default`, `bass_hz=180`, `mid_high_hz=3500`, and ordered `keyframes`. Each frame contains:

```json
{
  "time_s": 4.0,
  "mix": 0.5,
  "level": 1.0,
  "bass_a": 0.0,
  "bass_b": 1.0,
  "mid_a": 1.0,
  "mid_b": 1.0
}
```

Times are relative to the overlap, starting at zero and ending at `overlap_s`. Values are linearly interpolated. `mix` drives the normalized Mixxx fader; `level` controls overall gain; bass/mid fields multiply their respective track bands. All values are finite and in 0-1. Bass coefficients sum to at most 1. The first and final frames must join unmodified A and B. The renderer validates these conditions before decoding audio.

Plans from version 0.1 do not contain this automation. Regenerate those plans with version 0.2 rather than supplying them to the new renderer.

## Mix result

The result contains `output`, `report`, `audio_sha256`, `plan`, `analysis={a,b}`, and `validation`, with schema version 2. The complete object is saved to `OUT.mp3.json`; CLI stdout omits the long analysis curves.

Validation includes duration, sample rate, channel count, codec, decoded sample peak, clipped sample count, and per-track RMS gain. Decoded sample peak must be <=-1 dBFS and duration must match the plan within 150 ms. These checks do not measure intersample true peak, subjective quality, LUFS, or annotation accuracy.

## External feature sidecars

Obtain the original file hash with `analyze`. Bind external-model or manually verified results to it. Only the following fields are accepted; each feature field is optional:

```json
{
  "audio_sha256": "full SHA-256 of the original MP3 file",
  "downbeats": [0.0, 2.0, 4.0, 6.0],
  "vocal_activity": {"times_s": [0.0, 0.5, 1.0], "values": [0.0, 0.8, 0.9]},
  "section_boundaries": [0.0, 16.0, 32.0],
  "drops": [32.0]
}
```

This illustrates structure only. Actual vocal curves must cover the full track: first point <=0.5 s, last point >=duration minus 1.5 s, and gaps <=2 s. Supply the complete curve. Downbeats must identify consecutive 4/4 bar starts, contain at least two points, and match the base beat sequence within 80 ms. Drops must match the selected downbeats within 80 ms. An explicit `drops: []` disables estimated drops for that source. All times must increase, be finite, and lie in `[0,duration)`.

```bash
agent-mix mix A.mp3 B.mp3 -o dropped.mp3 --mode double_drop \
  --mixxx-db /path/to/mixxxdb.sqlite \
  --features-a A.features.json --features-b B.features.json --strict
```

The caller verifies external annotations. The program checks format, hash, and basic consistency, not model accuracy. Strict mode enforces annotation sources and musical rules, without guaranteeing listening quality.
