import importlib.util
from pathlib import Path
import sqlite3
import struct

import pytest


def varint(n):
    n &= (1 << 64) - 1
    result = bytearray()
    while n > 127:
        result.append((n & 127) | 128)
        n >>= 7
    result.append(n)
    return bytes(result)


def grid(bpm, first_frame=0):
    # BeatGrid { bpm { bpm: double }, first_beat { frame_position: int32 } }
    first = b"\x08" + varint(first_frame)
    return b"\x0a\x09\x09" + struct.pack("<d", bpm) + b"\x12" + varint(len(first)) + first


@pytest.fixture(scope="session")
def tracks(tmp_path_factory):
    directory = tmp_path_factory.mktemp("audio")
    spec = importlib.util.spec_from_file_location("demo", Path(__file__).parents[1] / "examples/synthetic_demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    a, b = directory / "a.mp3", directory / "b.mp3"
    demo.synthesize(a, 120)
    demo.synthesize(b, 124)
    database = directory / "mixxxdb.sqlite"
    with sqlite3.connect(database) as db:
        db.executescript('''
            CREATE TABLE track_locations(id INTEGER PRIMARY KEY, location TEXT);
            CREATE TABLE library(id INTEGER PRIMARY KEY,location INTEGER,bpm REAL,
              beats BLOB,beats_version TEXT,samplerate INTEGER,key_id INTEGER,
              duration REAL,mixxx_deleted INTEGER);
        ''')
        for index, path, bpm in [(1, a, 120), (2, b, 124)]:
            db.execute("INSERT INTO track_locations VALUES (?,?)", (index, str(path)))
            db.execute("INSERT INTO library VALUES (?,?,?,?,?,?,?,?,?)",
                       (index, index, bpm, grid(bpm), "BeatGrid-2.0", 44100, 1, 40, 0))
    return a, b, database
