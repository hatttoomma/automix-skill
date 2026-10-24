# Mixxx source mapping

Pinned upstream: `mixxxdj/mixxx`, tag `2.5.6`, commit `3ebac449e7e5fe2a0186596657696e87ce8b0e56`. The included [mixxx-beats.proto](mixxx-beats.proto) comes from this version.

| Local implementation | Mixxx source |
|---|---|
| Beat-blob wire layout | [src/proto/beats.proto](https://github.com/mixxxdj/mixxx/blob/3ebac449e7e5fe2a0186596657696e87ce8b0e56/src/proto/beats.proto) |
| BeatGrid-2.0, BeatMap-1.0, and FramePos coordinates | [src/track/beats.cpp](https://github.com/mixxxdj/mixxx/blob/3ebac449e7e5fe2a0186596657696e87ce8b0e56/src/track/beats.cpp) |
| Library-to-track_locations association | [src/library/dao/trackdao.cpp](https://github.com/mixxxdj/mixxx/blob/3ebac449e7e5fe2a0186596657696e87ce8b0e56/src/library/dao/trackdao.cpp) |
| key_id: 1-12 major, 13-24 minor | [src/proto/keys.proto](https://github.com/mixxxdj/mixxx/blob/3ebac449e7e5fe2a0186596657696e87ce8b0e56/src/proto/keys.proto) |
| Constant-power crossfader port | [src/engine/enginexfader.cpp](https://github.com/mixxxdj/mixxx/blob/3ebac449e7e5fe2a0186596657696e87ce8b0e56/src/engine/enginexfader.cpp) |

Native fixed-tempo grids are expanded from an anchor and interval. BeatMap data is decoded as explicit beat positions. This project does not modify Mixxx's real-time sync, AutoDJ, or C++ analyzers. The default crossfade computes `gA=1-t, gB=t`, then divides both by `sqrt(gA^2+gB^2)`. This specializes the upstream CONSTPWR branch with transform=1; other upstream curves are not ported.

Downbeat-phase estimation, energy curves, novelty boundaries, external vocal curves, candidate scoring, two-band bass swapping, and FFmpeg pitch-preserving offline rendering are additions in this project. No neural singing detector or semantic section model is bundled.
