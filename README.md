# automix-skill

An offline **2 MP3 -> 1 MP3** mixing API and coding-agent skill. The default `auto` mode compares transitions, sustained layering, vocal/bed mashups, and synchronized double drops, then renders the selected arrangement.

```python
from mixxx_agent_mix import mix

result = mix("a.mp3", "b.mp3", "mixed.mp3")  # mode="auto"
print(result["plan"]["mode"], result["plan"]["selection"]["reason"])
```

**Mixxx integration:** Native BPM, beat grids, beat maps, and keys come from a supplied Mixxx 2.5.6 database. The gain law is a Python port of Mixxx's default constant-power crossfader. FFmpeg decodes, changes tempo while preserving pitch, and encodes MP3; librosa supplies supplementary analysis. Gain/EQ arrangement automation and style selection are additions in this project. Without a database, an explicitly labelled librosa fallback is used. This project does not run Mixxx's C++ engine or expose an upstream offline mixing API. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Install and run

Requires Python 3.10+; Python 3.11 is recommended. FFmpeg is selected from `MIXXX_AGENT_FFMPEG`, the system `ffmpeg`, or the binary bundled with imageio-ffmpeg. It must include `libmp3lame` and `atempo`. The Mixxx GUI need not run.

```bash
git clone https://github.com/hatttoomma/automix-skill.git
cd automix-skill
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'

# Automatic style selection is the default.
agent-mix mix a.mp3 b.mp3 -o mixed.mp3
agent-mix plan a.mp3 b.mp3 --mode auto

# Request a particular style. Explicit requests fail if their requirements are unmet.
agent-mix mix a.mp3 b.mp3 -o layered.mp3 --mode layering --bars 16
agent-mix mix a.mp3 b.mp3 -o handoff.mp3 --mode transition

# Use native Mixxx analysis and external musical annotations.
agent-mix mix a.mp3 b.mp3 -o creative.mp3 --mode auto \
  --mixxx-db /path/to/mixxxdb.sqlite \
  --features-a a.features.json --features-b b.features.json

# Reproducible demo with original synthetic audio; no songs are downloaded.
python examples/synthetic_demo.py /tmp/agent-mix-demo
pytest -q
```

The output is a 44.1 kHz stereo MP3 at 320 kbps plus `mixed.mp3.json`. The report records feature sources, the selected style, alternatives and unavailable modes, gain/EQ automation, drop anchors, trimming, output hash, and decoded peak checks. Existing outputs and sidecars are never overwritten. CLI success returns JSON on stdout; handled errors return exit code 2 and JSON on stderr.

## Mixing modes

| Mode | Planning | Audible arrangement |
|---|---|---|
| `auto` (default) | Compare eligible modes using musical fit and disclosed creative preferences. | Render the winning mode and explain the selection. |
| `transition` | Search A's final 45% and B's first 35%. | Continuous Mixxx constant-power handoff with a bass swap. |
| `layering` | Search compatible, balanced windows across both tracks. | Fade in over the first quarter, hold both tracks over the middle half, then hand off to B. One track owns bass during the layer. |
| `mashup` | Require vocal curves identifying one vocal foreground and one mostly instrumental bed. | Hold the vocal/bed combination over the middle 75%; favor the foreground and attenuate the bed's midrange. The bed owns bass. |
| `double_drop` | Require a drop anchor in each track; align them after a shared preroll. | Introduce B during the buildup, bring both tracks forward at the shared drop, sustain the post-drop layer, then hand off. |

Layering, mashup, and double drop search the whole track rather than inheriting the transition-only intro/outro restriction. All modes preserve A -> B order, use one fixed target tempo, check the full beat sequence, and finish on B. See [mode rules and scoring](skills/mix-two-tracks/references/mixing-modes.md).

`auto` favors creative arrangements when evidence supports them, while retaining a transition fallback. Unknown vocal activity or incompatible keys caps the requested arrangement at 4 bars. Unknown vocals remain unknown: mashup is unavailable without vocal curves. Creative layering requires compatible keys. Double drop requires external markers or labelled energy/bass-rise estimates with heuristic confidence >=0.65; generic section boundaries alone do not qualify.

This is a **full-mix EQ mashup**, without vocal extraction or stem separation. It relies on naturally complementary source windows. Drop estimates are musical hypotheses rather than semantic ground truth; listen and supply verified markers when needed.

## Python interface

The distribution is `automix-skill`; the import remains `mixxx_agent_mix` and the CLI remains `agent-mix`.

```python
from mixxx_agent_mix import analyze, plan, mix

a = analyze("a.mp3", mixxx_db=None, features=None)
b = analyze("b.mp3", mixxx_db=None, features=None)
decision = plan(a, b, mode="auto", bars=8, strict=False, max_rate_change=0.08)

result = mix(
    "a.mp3", "b.mp3", "mixed.mp3",
    mode="auto",                  # auto / transition / layering / mashup / double_drop
    mixxx_db=None,                 # Explicit database errors never silently fall back.
    features_a=None, features_b=None,
    bars=8,                       # Total arrangement: 4 / 8 / 16 / 32 bars.
    strict=False,                 # Require external downbeats/vocals and compatible keys.
    max_rate_change=0.08,         # Keep A's BPM; change B's tempo by at most +/-8%.
)
```

Functions return JSON-compatible dictionaries and raise errors for file, decoding, analysis, planning, or validation failures. There is no HTTP server. Version 0.2 uses **schema version 2** for analyses, plans, and reports; the renderer executes the plan's automation keyframes. Regenerate persisted version-1 plans before rendering. See the [interface reference](skills/mix-two-tracks/references/interface.md).

## Features and annotations

| Feature | Source and use |
|---|---|
| BPM | Mixxx or librosa; limit tempo changes. |
| Beat timestamps | Native Mixxx frames converted to seconds or librosa; reject drift over 80 ms across the arrangement. |
| Downbeats | Estimated 4/4 bass-accent phase or external annotations; align bar starts. |
| Energy curve | STFT RMS dBFS aggregated every 0.5 seconds; assess balance, rises, and drop candidates. |
| Low-frequency energy | Relative 20-180 Hz energy; assess bass collisions and designate bass ownership. |
| Key | Mixxx `key_id` or chroma profiles; favor same key, same-mode fifth relationships, and relative major/minor. |
| Vocal activity | Externally supplied 0-1 curves, otherwise `null`; avoid vocal collisions and choose mashup roles. |
| Section boundaries | Chroma/energy novelty estimates or external timestamps; favor structural alignment without guessing verse/chorus labels. |
| Drop anchors | External timestamps or strong downbeat energy/bass-rise estimates; synchronize double drops. |

Supply external features with `--features-a` / `--features-b`. Sidecars bind to the original file's SHA-256. Vocal curves must cover the full track; downbeats must mark consecutive 4/4 bars. An optional `drops` array lists original-source downbeat times. An empty array explicitly disables estimated drops for that track. See [external feature sidecars](skills/mix-two-tracks/references/interface.md#external-feature-sidecars).

`--strict` requires external downbeats, full-track vocal curves, and compatible keys. For double drops, it also requires externally supplied drop markers. In strict auto mode, estimated-only double drops are skipped while other qualified modes can still win. Explicit mode requests never silently switch styles.

The Mixxx database path must be supplied explicitly. Reads use a read-only connection and an in-memory snapshot including committed WAL data; analysis is never written back. Both tracks must be imported, analyzed, and match their stored paths. Reanalyze changed files: stale analysis of a same-duration replacement cannot be detected from duration alone. Supported beat formats are `BeatGrid-2.0` and `BeatMap-1.0`, pinned to Mixxx 2.5.6; legacy and unknown formats fail explicitly.

## Output timeline and DSP

Every result keeps A from its start through the arrangement, discards A's remaining tail, starts B at the selected entry, and retains B's remainder. Output duration is approximately `exit_A + (duration_B - entry_B) / rate_B`. Creative modes may trim more of a track to reach a suitable section; inspect the reported source times.

Automation uses source mix position, overall level, and separate bass/midrange gains. Each gain pair uses Mixxx's default constant-power law. Offline zero-phase complementary bands at 180 Hz and 3500 Hz support bass ownership and vocal/bed EQ without changing beat positions. Both full bass bands are never enabled together. B remains pitch-preserving; no pitch shift is introduced. Per-track RMS gain is bounded to approximately +/-6 dB. MP3 decoding verifies sample peak <=-1 dBFS and duration within 150 ms of the plan.

## Install the agent skill

Install this package in the agent's Python environment, then copy the skill:

```bash
mkdir -p ~/.codex/skills
cp -R skills/mix-two-tracks ~/.codex/skills/
```

Invoke `$mix-two-tracks` in Codex, or provide [SKILL.md](skills/mix-two-tracks/SKILL.md) to another coding agent. The skill defaults to automatic style selection and can honor an explicit requested style. No API key or chat service is required.

## Limits and validation

- In-memory processing; each original track and tempo-adjusted B is limited to 15 minutes.
- Fixed-tempo, 4/4 arrangements with one overlapping region. There is no arbitrary looping, multi-song sequencing, local pitch shifting, or stem generation.
- Keys are track-global; local key modulation is not modeled.
- No bundled neural singing/downbeat/drop model. Speech VAD is not reliable singing detection. Heuristic confidence is not calibrated probability.
- RMS matching is not LUFS normalization. Decoded sample peak is not intersample true peak. Beat-grid checks and clipping checks do not guarantee musical quality.
- Tests cover automatic selection of all four modes, whole-track creative anchors, tempo-adjusted drop synchronization, vocal/bed roles, audible layer/EQ behavior, annotations, rejection conditions, and real MP3 rendering for every mode. Listening evaluation on commercial songs and Mixxx GUI integration are outside the tested scope.

GPL-2.0-or-later. No user songs, private Mixxx library data, or model weights are committed.
