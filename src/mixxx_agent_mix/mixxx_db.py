# SPDX-License-Identifier: GPL-2.0-or-later
"""Read Mixxx 2.5.6 BeatGrid-2.0 / BeatMap-1.0 without modifying its library.

Wire layout and key enum: mixxxdj/mixxx src/proto/{beats,keys}.proto.
FramePos is an audio FRAME, so divide by native sample rate, never by channels.
"""
from pathlib import Path
import math
import sqlite3
import struct
import time

import numpy as np


def _varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError("Truncated Mixxx protobuf")
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError("Invalid Mixxx protobuf varint")


def _fields(data):
    """Minimal bounded protobuf reader; skips unknown scalar/message fields."""
    pos, result = 0, {}
    while pos < len(data):
        tag, pos = _varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0:
            raise ValueError("Invalid Mixxx protobuf field")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                length, pos = _varint(data, pos)
            else:
                length = 8 if wire == 1 else 4
            end = pos + length
            if end > len(data):
                raise ValueError("Truncated Mixxx protobuf value")
            value, pos = data[pos:end], end
        else:
            raise ValueError("Unsupported Mixxx protobuf wire type")
        result.setdefault(field, []).append((wire, value))
    return result


def _get(fields, number, wire):
    actual, value = fields[number][-1]
    if actual != wire:
        raise ValueError("Wrong Mixxx protobuf field type")
    return value


def _frame(message):
    # protobuf int32 negative values use a sign-extended varint.
    value = _get(_fields(message), 1, 0) & 0xffffffff
    return value - 2**32 if value >= 2**31 else value


def decode_beats(blob, version, sample_rate, duration):
    if not sample_rate or sample_rate <= 0:
        raise ValueError("Mixxx native sample rate is missing")
    try:
        fields = _fields(blob)
        if version == "BeatGrid-2.0":
            bpm = struct.unpack("<d", _get(_fields(_get(fields, 1, 2)), 1, 1))[0]
            anchor = _frame(_get(fields, 2, 2)) / sample_rate
            if not math.isfinite(bpm) or not 20 <= bpm <= 400:
                raise ValueError("Invalid Mixxx BPM")
            step = 60 / bpm
            first = anchor + math.ceil(-anchor / step) * step
            beats = np.arange(first, duration, step)
        elif version == "BeatMap-1.0":
            beats = np.array([_frame(data) / sample_rate for wire, data in fields[1]
                              if wire == 2], dtype=float)
            if len(beats) < 2 or np.any(np.diff(beats) <= 0):
                raise ValueError("Unordered Mixxx beat map")
            bpm = 60 / float(np.median(np.diff(beats)))
        else:
            # Legacy BeatGrid-1.0 has a platform-dependent raw-double fallback.
            raise ValueError(f"Unsupported beats version {version!r}; reanalyze in Mixxx 2.5")
    except (KeyError, TypeError, struct.error) as exc:
        raise ValueError("Incomplete Mixxx beat data") from exc
    beats = beats[(beats >= 0) & (beats < duration)]
    if not math.isfinite(bpm) or not 20 <= bpm <= 400:
        raise ValueError("Invalid Mixxx BPM")
    if len(beats) < 8:
        raise ValueError("Mixxx analysis contains fewer than 8 usable beats")
    return float(bpm), beats.tolist()


def read_track(database, path, duration):
    """Exact resolved path lookup; explicit database requests fail instead of falling back."""
    db = Path(database).expanduser().resolve(strict=True)
    # SQLite online backup yields a consistent snapshot, including committed WAL data.
    source = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=5)
    snapshot = sqlite3.connect(":memory:")
    try:
        deadline = time.monotonic() + 8
        def check_deadline(status, remaining, total):
            if time.monotonic() > deadline:
                raise ValueError("Mixxx snapshot timed out; close Mixxx and retry")
        source.backup(snapshot, pages=128, progress=check_deadline)
        snapshot.row_factory = sqlite3.Row
        rows = snapshot.execute(
            'SELECT l.bpm,l.beats,l.beats_version,l.samplerate,l.key_id,l.duration '
            'FROM library l JOIN track_locations t ON l.location=t.id '
            'WHERE t.location=? AND COALESCE(l.mixxx_deleted,0)=0',
            (str(Path(path).expanduser().resolve()),),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("Track is missing or ambiguous in the requested Mixxx database")
        row = rows[0]
        if row["duration"] and abs(row["duration"] - duration) > 1.0:
            raise ValueError("Mixxx duration differs from decoded audio; reanalyze the file")
        bpm, beats = decode_beats(row["beats"], row["beats_version"], row["samplerate"], duration)
        key_id = row["key_id"] or 0
        key = None
        if 1 <= key_id <= 24:
            key = {"tonic": (key_id - 1) % 12,
                   "mode": "major" if key_id <= 12 else "minor", "confidence": None}
        return {"bpm": bpm, "beat_timestamps": beats, "key": key}
    except sqlite3.Error as exc:
        raise ValueError(f"Unsupported or unreadable Mixxx library: {exc}") from exc
    finally:
        source.close()
        snapshot.close()
