# Mixing modes and automatic selection

## Shared constraints

`mode="auto"` is the default. All modes preserve A -> B playback order, target A's BPM, apply one fixed pitch-preserving rate to B, and require every beat in the arrangement to align within 80 ms. Default maximum rate change is +/-8%. Valid lengths are 4, 8, 16, or 32 bars in 4/4.

Unknown vocals or incompatible keys reduce the requested length to at most 4 bars. Incompatible keys disqualify creative modes but may permit a warned short transition. Known vocal curves reject windows with mean minimum vocal activity above 0.25; layering and mashup impose tighter conditions. Unknown activity remains null and produces a warning.

`strict=True` requires external downbeats, full-track vocal curves, and compatible keys. Double drop additionally requires external drop markers. Explicit modes never fall back to another style. Auto compares all eligible styles and reports reasons for unavailable ones.

## Transition

Search A's final 45% and B's first 35%, preserving at least two seconds of B after the fade. Apply a continuous constant-power crossfade. Bass ownership moves from A to B across 40%-60% of the arrangement. Large energy differences are scored and warned rather than automatically rejected.

## Layering

Search downbeats across both tracks. Require compatible keys, median energy difference <=6 dB, and known vocal collision <=0.15 when vocal information exists. Unknown vocals permit at most 4 bars with a listening warning.

The first quarter introduces B; the middle half holds a constant mix position of 0.5, giving both tracks approximately 0.707 broadband gain before band EQ; the final quarter hands off to B. The source with greater mean bass energy owns bass during the plateau; B wins ties. Bass ownership transitions smoothly at entry/exit. There is no loop or stem separation.

## Mashup

Search both tracks for a natural vocal/bed pairing. Require compatible keys and full-track vocal curves. Within a candidate window:

- Foreground mean vocal activity >=0.5.
- Bed mean vocal activity <=0.15.
- Difference in mean vocal activity >=0.4.
- Mean minimum vocal activity <=0.15.

The middle 75% sustains the combination. Mix position is 0.35 for foreground A or 0.65 for foreground B. The instrumental bed owns bass and its 180-3500 Hz midrange gain is 0.45 during the hold; the foreground midrange remains at 1.0. Entry and exit return to unmodified A and B respectively.

This is a full-mix EQ mashup, not vocal extraction. Curves identify useful source windows; they do not remove residual singing, melodies, or percussion from either recording.

## Double drop

Require one eligible drop marker per track, both with confidence >=0.65. External markers have confidence 1.0 by caller assertion. Automatic markers are labelled energy/bass-rise estimates, not calibrated probabilities. Strict mode accepts only external markers.

The preroll is `min(2, max(1, bars // 4))` bars: one bar for a 4-bar arrangement and two bars otherwise. Define:

```text
start_A = drop_A - preroll_seconds
start_B = drop_B - preroll_seconds * rate_B
shared_drop_output = start_A + preroll_seconds
```

Both source windows must fit and pass the entire beat-alignment check. During preroll, B is introduced softly; the overall level dips to 0.85 one beat before the drop. At the shared drop, mix position becomes 0.5 and overall level returns to 1.0. Both tracks hold until 75% of the arrangement, followed by the handoff to B. One bass owner is selected by mean low-frequency energy.

Automatic marker estimation examines downbeats with two bars of context before them and one bar after. A candidate needs a median RMS energy rise >=4.5 dB and relative bass-energy rise >=0.08. Confidence is `min(0.95, 0.45 + energy_rise_db/30 + bass_rise*0.5)`. Strongest estimates are spaced by at least four bars. A novelty boundary without these conditions is not a drop. Drops without strong energy/bass rises need external annotation.

## Scores and explainability

Lower cost is preferred. Common terms include median energy difference, bass collision, distance to section boundaries, trimming, beat-alignment error, and vocal collision. Unknown vocals incur an uncertainty penalty. Mashup gains a vocal-role contrast benefit; estimated drop confidence affects double-drop cost.

Style priors are transition=0.5, layering=0.3, mashup=0.2, and double_drop=0.12. They express a creative preference after eligibility checks rather than acoustic-quality probabilities. Shared terms can outweigh those priors. Auto retains the best candidate for each mode, ranks those candidates, and reports `selection.alternatives` and per-mode evaluation counts/reasons. It does not fabricate a creative mode when its requirements fail.

Whole-track searches are bounded to 64 source anchors per track when necessary, combining section-adjacent and evenly spaced downbeats. Drop search uses supplied/estimated markers directly.

## Renderer contract

A schema-2 plan supplies `automation.keyframes`. Each frame has `time_s`, `mix`, `level`, `bass_a`, `bass_b`, `mid_a`, and `mid_b`. Linear interpolation drives Mixxx's default constant-power mix law plus offline zero-phase complementary 180 Hz / 3500 Hz bands. High bands follow broadband track gain. Bass coefficients sum to at most 1; endpoint automation joins full A and full B without gain/EQ discontinuities. The shared drop is a keyframe, so drop synchronization and post-drop layering are rendered rather than merely described.
