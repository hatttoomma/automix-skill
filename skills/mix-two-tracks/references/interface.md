# Interface and JSON fields

## CLI

```bash
agent-mix analyze A.mp3 [--mixxx-db DB] [--features A.features.json]
agent-mix plan A.mp3 B.mp3 [--mixxx-db DB] [--features-a FILE] [--features-b FILE] [--bars 8] [--strict]
agent-mix mix A.mp3 B.mp3 -o OUT.mp3 [the same options]
```

`plan` and `mix` also accept `--max-rate-change 0.08`. Success returns exit code 0 and JSON on stdout. Handled input, planning, or output failures return exit code 2 and `{"error":"..."}` on stderr. Planning does not render audio. Mixing writes an MP3 and an adjacent sidecar. Existing output or report files cause failure.

## Analysis object

| Field | Meaning |
|---|---|
| `schema_version` | 1. |
| `path`, `audio_sha256` | Local input path and SHA-256 of the encoded input file. |
| `duration_s`, `bpm` | Decoded duration and estimated or native Mixxx BPM. |
| `beat_timestamps`, `downbeats` | Strictly increasing timestamp arrays in original audio seconds. |
| `energy_curve` | `times_s`, `values`, and `unit=dBFS_rms`. |
| `low_frequency_energy` | The same curve structure; relative 20-180 Hz energy normalized to P95, in 0-1. This is not absolute sound pressure. |
| `key` | `tonic` ranges from C=0 to B=11; `mode` is `major/minor`. `confidence` is a correlation score or null, not a calibrated probability. The entire object may be null. |
| `vocal_activity` | Null or `{times_s, values}`, with externally supplied 0-1 vocal activity values. |
| `section_boundaries` | Boundary times in original audio seconds, without semantic labels. |
| `sources` | Per-feature provenance distinguishing mixxx, librosa, estimated, external, and unknown. |

Energy curves have approximately one point every 0.5 seconds. Arrays use the decoded audio timeline, excluding MP3 encoder-delay metadata; FFmpeg handles gapless decoding. Convert native Mixxx positions with `frame_position / native_samplerate`. Do not divide by channel count or substitute the analysis resampling rate for the original sample rate.

## Plan object

Key fields are `target_bpm`, `rate_a=1`, `rate_b`, `exit_a_s`, `entry_b_s`, `overlap_s`, `bars`, `requested_bars`, and `expected_duration_s`. `rate_b=target_bpm/BPM_B`; values above 1 speed B up. B's entry is in original source time. Its overlap window spans `overlap_s * rate_b` seconds in the original B audio.

`score_components` contains energy difference, bass and vocal collisions, and maximum beat-alignment error. Vocal collision is null when vocal activity is unknown. Review `warnings`. The planner uses a global track key and does not model local key changes.

## Mix result

The result contains `output`, `report`, `audio_sha256`, `plan`, `analysis={a,b}`, and `validation`. The complete object is saved to `OUT.mp3.json`. CLI stdout contains only output, report, plan, and validation to avoid printing all feature curves.

`validation` includes duration, sample rate, channel count, MP3 codec, decoded sample peak, clipped sample count, and per-track RMS gain. The decoded sample-peak ceiling is -1 dBFS and duration tolerance is 150 ms. These checks do not measure intersample true peak, subjective quality, LUFS, or vocal-detection accuracy.

## External feature sidecars

Use `analyze` to obtain the original file hash. Bind external-model or manually verified results to that hash. Only these fields are accepted; each feature field is optional:

```json
{
  "audio_sha256": "full SHA-256 of the original MP3 file",
  "downbeats": [0.0, 2.0, 4.0, 6.0],
  "vocal_activity": {"times_s": [0.0, 0.5, 1.0], "values": [0.0, 0.8, 0.9]},
  "section_boundaries": [0.0, 16.0, 32.0]
}
```

This example illustrates structure only. Actual vocal curves must cover the entire track: the first point must be at most 0.5 s, the final point at least duration minus 1.5 s, and adjacent gaps at most 2 s. Supply the complete curve rather than the three example points. Downbeats must identify consecutive 4/4 bar starts, include at least two points, and agree with the underlying beat timestamps within 80 ms. All times must be finite, increasing, and in `[0,duration)`; do not include an endpoint exactly equal to duration.

```bash
agent-mix mix A.mp3 B.mp3 -o verified.mp3 \
  --mixxx-db /path/to/mixxxdb.sqlite \
  --features-a A.features.json --features-b B.features.json --strict
```

The caller supplies and verifies external curves. The program validates their format, hash, and basic consistency, not the external model's accuracy. Strict mode enforces sources and planning rules; it does not guarantee listening quality.
