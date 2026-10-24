---
name: mix-two-tracks
description: Mix two local MP3s into one arrangement, automatically choosing a transition, sustained layering, a vocal/bed mashup, or a synchronized double drop from beat, key, energy, vocal, and section evidence. Use for two-track DJ mixing and creative arrangement revisions.
---

# Mix two tracks

Use the installed `automix-skill` package and `agent-mix` CLI. The default is **`--mode auto`**: actively compare creative arrangements and a conventional transition, then deliver one MP3 and its JSON report. Honor an explicitly requested style with `--mode transition|layering|mashup|double_drop`; an unmet explicit request must fail visibly rather than silently become a crossfade.

If the CLI is missing from PATH, use `python -m mixxx_agent_mix.cli` in the package's environment. If the package is absent, run `python -m pip install -e .` from this repository.

## Workflow

1. Establish A -> B order and a new output path. Preserve the user's track order unless directed otherwise. Pass a supplied Mixxx database with `--mixxx-db`; otherwise permit the labelled librosa fallback.
2. Run `agent-mix plan A.mp3 B.mp3 --mode auto --bars 8`, with any supplied `--features-a` / `--features-b`. Read `mode`, `selection.reason`, alternatives, unavailable reasons, roles, source times, drop anchors, and automation. For style criteria, read [references/mixing-modes.md](references/mixing-modes.md).
3. Prefer a musically supported creative arrangement. Do not force a mashup without vocal/bed evidence or a double drop without two drop anchors. Unknown vocals may permit a short warned layer, but do not imply an instrumental track. Use `--strict` when verified external annotations are required.
4. Render with `agent-mix mix A.mp3 B.mp3 -o MIX.mp3 --mode auto --bars 8`, using the same planning options. The renderer executes the chosen mode's gain and EQ keyframes, including sustained layers; increasing crossfade duration alone does not create a mashup or double drop.
5. Check `validation` and `plan.warnings`. Deliver the MP3 and JSON and explain the selected style, rejected alternatives when relevant, target BPM, B's tempo ratio, overlap bars, roles/drop synchronization, and trimming. Listen around the arrangement when playback is available.

## Musical decisions

- **BPM and beats:** Keep A's tempo; change B's tempo while preserving pitch, normally within +/-8%. Reject arrangements exceeding 80 ms beat-grid error anywhere in the overlap. Do not hide drift with average BPM or guess half/double tempo.
- **Layering:** Encourage sustained coexistence when keys, energy, and vocal occupancy fit. Search both tracks beyond intro/outro regions. Keep one bass owner and use a genuine fixed-mix plateau between entry and exit ramps.
- **Mashup:** Use vocal curves to choose a vocal foreground and a mostly instrumental bed. Favor the foreground, attenuate bed midrange, and give bass to the bed. Explain that this is full-mix EQ layering; do not promise isolated vocals or generated stems.
- **Double drop:** Align two supplied or explicitly labelled estimated drop anchors after a shared preroll. Hold both tracks after the common drop with one bass owner. Section boundaries alone are insufficient. Verified external drop markers are required in strict mode.
- **Downbeats and sections:** Align 4/4 bar starts and favor section boundaries. Estimated bass-accent phase may be wrong; do not invent verse/chorus labels.
- **Energy, keys, and vocals:** Score complementary energy and roles rather than penalizing every overlap. Avoid simultaneous foreground vocals and full bass stacking. Incompatible keys or unknown vocals cap the arrangement at 4 bars; mashup requires known vocal curves, and creative modes require compatible keys. Do not add pitch shifting without direction.

## Interface and boundaries

Read [references/interface.md](references/interface.md) for schema-2 plans, source-time coordinates, automation, and external sidecars. Source annotations are tied to the original MP3 hash; optional `drops` timestamps must agree with downbeats. Preserve uncertainty in feature provenance and warnings.

The output retains A through the arrangement, discards its remaining tail, and retains B from the chosen entry onward. Creative anchors can trim substantial material; report the actual source times. B's source durations are divided by `rate_b` in rendered time.

This project bridges Mixxx data and ports its default gain law; FFmpeg performs offline rendering. Do not invent a native Mixxx render API or singing/drop detector. See [references/mixxx-source.md](references/mixxx-source.md).

Never overwrite sources or existing outputs. Only publish generated music when the user requests publication. Peak validation and passing tests do not replace listening.
