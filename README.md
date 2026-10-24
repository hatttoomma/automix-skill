# automix-skill

A minimal offline **2 MP3 -> 1 MP3** mixing API and skill for coding agents.

```python
from mixxx_agent_mix import mix

result = mix("a.mp3", "b.mp3", "mixed.mp3")
print(result["output"], result["report"])
```

**Mixxx integration:** This project reads native BPM, beat grids, beat maps, and keys from Mixxx 2.5.6 and ports its default constant-power crossfader formula. FFmpeg handles decoding, pitch-preserving tempo changes, and MP3 encoding; librosa provides supplementary analysis. This is an offline bridge rather than a headless Mixxx player. It does not wrap an upstream offline `mix()` API. Without a database, it uses an explicitly labelled librosa fallback. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for provenance.

## Install and run

Requires Python 3.10+; Python 3.11 is recommended. The Mixxx GUI does not need to be running. FFmpeg is selected from `MIXXX_AGENT_FFMPEG`, then the system `ffmpeg`, then the binary bundled with imageio-ffmpeg. The selected build must include `libmp3lame` and `atempo`.

```bash
git clone https://github.com/hatttoomma/automix-skill.git
cd automix-skill
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'

# Mix in one command. Success returns JSON on stdout.
# Handled errors return exit code 2 and JSON on stderr.
agent-mix mix a.mp3 b.mp3 -o mixed.mp3

# Use existing Mixxx analysis. Both tracks must be imported and analyzed,
# and their stored paths must match the supplied files.
agent-mix mix a.mp3 b.mp3 -o mixed-native.mp3 --mixxx-db /path/to/mixxxdb.sqlite

# Inspect features and the transition decision without rendering audio.
agent-mix analyze a.mp3 > a.analysis.json
agent-mix plan a.mp3 b.mp3 --bars 8

# Run a reproducible demo using original synthetic audio.
python examples/synthetic_demo.py /tmp/agent-mix-demo
pytest -q
```

The output is a 44.1 kHz stereo MP3 at 320 kbps plus `mixed.mp3.json`. The report contains both tracks' features and their sources, transition parameters, trimming details, warnings, the output hash, and decoded peak checks. Existing output files and sidecars are never overwritten.

## Agent interface

The distribution is named `automix-skill`; the Python import remains `mixxx_agent_mix`, and the CLI is `agent-mix`.

```python
from mixxx_agent_mix import analyze, plan, mix

a = analyze("a.mp3", mixxx_db=None, features=None)
b = analyze("b.mp3", mixxx_db=None, features=None)
decision = plan(a, b, bars=8, strict=False, max_rate_change=0.08)

result = mix(
    "a.mp3", "b.mp3", "mixed.mp3",
    mixxx_db=None,                 # An explicit database must be readable; no silent fallback.
    features_a=None, features_b=None,
    bars=8,                       # 4 / 8 / 16 / 32; uncertainty may reduce this to 4.
    strict=False,                 # Require external downbeats/vocals and compatible keys.
    max_rate_change=0.08,         # Keep A's BPM; change B's tempo by at most +/-8%.
)
```

Synchronous functions return ordinary JSON-compatible dictionaries and raise errors for file access, decoding, beat analysis, planning, or output validation failures. The CLI uses the same functions; no HTTP service is required. See the [interface reference](skills/mix-two-tracks/references/interface.md) for fields and time coordinates.

| Feature | Implementation and use |
|---|---|
| BPM | Mixxx beat grid/map or librosa; limits tempo changes. |
| Beat timestamps | Native Mixxx audio frames converted to seconds, or librosa beat tracking; checks drift across the full transition. |
| Downbeats | Estimated 4/4 bass-accent phase, overridable with external results; aligns bar starts. |
| Energy curve | STFT RMS in dBFS, aggregated every 0.5 seconds; penalizes abrupt energy changes. |
| Low-frequency energy | 20-180 Hz energy normalized to each track's P95; scores bass collisions and guides bass handoff. |
| Key | Mixxx `key_id` or a chroma-profile estimate; favors the same key, same-mode fifth relationships, or relative major/minor. |
| Vocal activity | Defaults to `null/unknown`; accepts model-generated or manually verified 0-1 curves to avoid overlapping vocals. |
| Section boundaries | Estimated chroma/energy novelty boundaries, overridable with external results; favors transitions near sections. |

Mixxx database locations depend on the system and configuration. Supply the path explicitly; the program does not scan private libraries. It opens a read-only connection and makes an in-memory snapshot, including committed WAL data, without writing analysis back. Database analysis may be stale: replacing a file with another of the same duration cannot be detected from duration alone, so reanalyze changed files in Mixxx. `BeatGrid-1.0` and unknown formats are explicitly rejected. Compatibility is based on Mixxx 2.5.6 rather than assumed for all future versions.

## Default mixing rules

1. Preserve the A -> B input order, 4/4 meter, and a constant transition tempo. Use A's BPM as the target. Reject B if the required tempo change exceeds +/-8%; do not automatically guess half/double tempo or shift pitch.
2. Choose downbeat starts within A's final 45% and B's first 35%. Request 8 bars by default. Check every beat across the overlap and reject candidates that deviate more than 80 ms from the target grid.
3. When vocal curves are available, reject windows where `mean(min(vocal_A, vocal_B)) > 0.25`. Unknown vocals or incompatible keys limit the overlap to 4 bars and produce warnings. Unknown vocal activity is never treated as silence.
4. Score vocal collisions, energy differences, bass overlap, distance to section boundaries, and trimming. The report records the components and final score; the score is not a probability of good sound.
5. Apply Mixxx's default constant-power gains and a two-band 180 Hz bass handoff across 40%-60% of the overlap. Apply bounded per-track RMS gain matching, then ensure the decoded MP3 sample peak is at most -1 dBFS.

**Trimming:** Keep A from its beginning through the end of the transition, discarding its remaining tail. Start B at the selected entry and retain everything after it. Output duration is approximately `exit_A + (duration_B - entry_B) / rate_B`. This is a sequential DJ transition that trims the tracks.

## Install the skill

First install this package in the Python environment used by your agent, then copy the skill:

```bash
mkdir -p ~/.codex/skills
cp -R skills/mix-two-tracks ~/.codex/skills/
```

Invoke `$mix-two-tracks` in Codex, or provide [SKILL.md](skills/mix-two-tracks/SKILL.md) directly to another coding agent. The skill requires this package's `agent-mix` command and does not need a chat service or API key.

## External vocal, downbeat, and section results

General speech VAD is not reliable singing detection. This MVP does not bundle neural vocal or downbeat models. For more reliable results, generate a sidecar using an external model or manual verification, then pass it through `--features-a` / `--features-b`. See [external feature sidecars](skills/mix-two-tracks/references/interface.md#external-feature-sidecars).

`--strict` fails when external downbeats or vocal curves are missing, or keys are incompatible. Normal mode permits output with warnings and still requires listening. Section output contains candidate boundary times, without guessed verse/chorus/drop labels.

## Limits and validation scope

- This is an in-memory MVP. Each original track and the tempo-adjusted B are limited to 15 minutes. Split longer tracks first; this is not a streaming production service.
- Transitions use a fixed tempo. Arbitrary free-tempo music, 3/4, complex meters, local pitch changes, and vocal separation are unsupported.
- RMS matching is not LUFS loudness normalization. Decoded sample peak is not intersample true peak.
- Analysis and scoring do not guarantee listening quality. Tests use original synthetic audio and cover native/fallback MP3 end-to-end paths, beat blobs, pitch-preserving tempo changes, vocal collisions, rejection conditions, and output protection. Commercial-song listening evaluation and Mixxx GUI integration are outside the tested scope.

GPL-2.0-or-later. The repository contains no user songs, private Mixxx library data, or model weights.
