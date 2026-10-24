# Third-party provenance

This repository is distributed under GPL-2.0-or-later; see LICENSE.

## Mixxx

Mixxx, Copyright (C) 2001–2026 Mixxx Development Team.
Upstream: https://github.com/mixxxdj/mixxx
Tag: 2.5.6. Commit: 3ebac449e7e5fe2a0186596657696e87ce8b0e56.
License: GNU General Public License, version 2 or (at your option) any later version.

- `src/mixxx_agent_mix/render.py::crossfade_gains` is a Python adaptation and
  specialization of `src/engine/enginexfader.cpp::EngineXfader::getXfadeGains`
  for default transform=1, CONSTPWR, reverse=false. Mode selection, gain/EQ
  automation, sustained layering, full-mix mashups, synchronized double drops,
  file handling and output verification are additions.
- `src/mixxx_agent_mix/mixxx_db.py` reads the serialization contract in
  `src/proto/beats.proto`, `src/track/beats.cpp`, `src/proto/keys.proto` and
  the database association in `src/library/dao/trackdao.cpp`.
- `skills/mix-two-tracks/references/mixxx-beats.proto` is an unmodified copy of
  the upstream `src/proto/beats.proto` from the pinned commit.

The complete corresponding Python source and copied schema are included here.
Mixxx itself, its GUI, C++ engine, plugins, skins and bundled libraries are not
redistributed with this project. See the pinned source links in the skill references.

## Runtime dependencies

NumPy, SciPy, librosa, soundfile and imageio-ffmpeg are installed as dependencies
and retain their own licenses. FFmpeg is an external executable; its licensing
depends on the selected build. No FFmpeg binary, model weights, user music or
private library data are committed to this repository.
