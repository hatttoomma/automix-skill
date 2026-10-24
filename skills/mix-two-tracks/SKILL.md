---
name: mix-two-tracks
description: Mix two local MP3 tracks into one offline DJ transition using Mixxx beats and keys, energy, downbeats, vocals, and section information. Use for sequential two-track mixing and transition revisions.
---

# Mix two tracks

Use the installed `automix-skill` package and `agent-mix` CLI. Produce one MP3 and an inspectable JSON report. If the CLI is unavailable on PATH, run `python -m mixxx_agent_mix.cli` with the Python environment where the package is installed. If the package is missing, run `python -m pip install -e .` from this repository.

## Workflow

1. Establish A -> B order and a new output path. If the user supplies only two tracks, preserve their order. Pass a user-provided Mixxx database through `--mixxx-db` to read native BPM, beats, and key. Otherwise allow the librosa fallback and state the feature sources.
2. Review the decision with `agent-mix plan A.mp3 B.mp3 --bars 8`. Use the same database and external-feature options for planning and mixing. Read [references/interface.md](references/interface.md) when field definitions or external-model result formats are needed.
3. Apply the rules below. Use the implementation's conservative fallback for missing features; use `--strict` when external downbeat and vocal information is required. Explain concrete failures rather than relaxing thresholds without justification.
4. Run `agent-mix mix A.mp3 B.mp3 -o MIX.mp3 --bars 8`, including the selected database, sidecar, and strict options. Check `validation`, `plan.warnings`, and the report file.
5. Deliver the audio and JSON. Briefly report target BPM, B's tempo ratio, A's exit, B's entry, overlap bars, trimming, and material uncertainty. When playback is available, listen around the transition; automated peak validation does not establish listening quality.

## Mixing rules

- **BPM / beat timestamps:** Keep A's tempo and change B's tempo while preserving pitch, by at most 8% by default. Check every beat across the overlap and reject candidates with more than 80 ms of grid error. Reject variable-tempo material that cannot be aligned with one fixed rate; average BPM does not resolve drift.
- **Downbeats / section boundaries:** Align 4/4 bar starts, usually over 8 or 16 bars, favoring section boundaries. Bass-accent phase is an estimate and may not identify the true first beat. Without a semantic model, do not label boundaries as verses or choruses.
- **Energy curve:** Avoid abrupt energy changes. Compare transition windows rather than whole-track averages. Flag differences above 6 dB for listening review. RMS gain matching is bounded to approximately +/-6 dB.
- **Low-frequency energy:** Avoid stacking two full bass parts. Use the 180 Hz bass handoff and Mixxx's default constant-power crossfade; inspect the bass-collision score.
- **Key:** Favor the same key, same-mode fifth relationships, or relative major/minor. Unknown or incompatible keys limit the overlap to 4 bars and require a warning. Do not introduce pitch shifting without user direction.
- **Vocal activity:** With full-track vocal curves, reject overlap windows where `mean(min(A,B)) > 0.25`. Keep unknown activity as `null`, limit the overlap to 4 bars, and recommend listening. Speech VAD and mid-frequency spectral energy cannot establish the absence of singing.

## Output boundaries

The result discards A's tail after the transition and B's intro before its entry. Explain that trimming when delivering the result. Feature timestamps use seconds in each original source; divide B's source durations by `rate_b` to obtain rendered durations.

This is a Mixxx data bridge and a port of its default crossfader, with FFmpeg offline rendering. Do not invent `mixxx --render`, a REST API, or native vocal/section detection. See [references/mixxx-source.md](references/mixxx-source.md) for the source mapping. An explicitly requested database read must fail visibly rather than silently switching analysis sources.

Do not overwrite source tracks or existing results. Upload generated music only when the user requests publication; local mixing does not authorize public audio uploads.
