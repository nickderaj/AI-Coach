"""Shared fixtures."""

import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from trainer.storage.database import connect, migrate

# The subset of the v1 gym bot schema the importer reads.
V1_SCHEMA = """
CREATE TABLE movements (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL, modality TEXT NOT NULL, muscle_groups TEXT, equipment TEXT,
    default_unit TEXT);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, started_at DATETIME NOT NULL, ended_at DATETIME,
    kind TEXT NOT NULL, notes TEXT);
CREATE TABLE session_items (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL,
    position INTEGER NOT NULL, movement_id INTEGER NOT NULL);
CREATE TABLE efforts (id INTEGER PRIMARY KEY, session_item_id INTEGER NOT NULL,
    position INTEGER NOT NULL, reps INTEGER, weight_kg REAL, duration_s REAL, distance_m REAL,
    rpe INTEGER, notes TEXT);
CREATE TABLE body_metrics (id INTEGER PRIMARY KEY, date DATETIME NOT NULL, metric TEXT NOT NULL,
    value REAL NOT NULL, unit TEXT NOT NULL);
"""

# Shapes seen in the real v1 data: naive UTC and offset timestamps, a timed
# exercise, a cardio session, a merged session with ended_at, and effort notes.
V1_ROWS = """
INSERT INTO movements VALUES
    (8, 'barbell bench press', 'Barbell Bench Press', 'strength', 'chest,triceps', 'barbell', 'kg'),
    (23, 'dead hang', 'Dead Hang', 'strength', 'grip', 'bodyweight', 's'),
    (45, 'lat pulldown', 'Lat Pulldown', 'strength', 'back,biceps', 'cable', 'kg'),
    (17, 'pullup', 'Pull-up', 'strength', 'back,biceps', 'bodyweight', 'kg'),
    (60, 'pilates', 'Pilates', 'cardio', NULL, NULL, NULL);
INSERT INTO sessions VALUES
    (1, '2026-07-09 10:47:23', NULL, 'strength', 'first'),
    (2, '2026-08-17T12:36:06.923574+01:00', '2026-08-17T13:09:54+01:00', 'strength', 'good'),
    (3, '2026-08-06T15:50:50+01:00', NULL, 'cardio', 'reformer');
INSERT INTO session_items VALUES
    (10, 1, 1, 8), (11, 1, 2, 23), (20, 2, 1, 45), (21, 2, 2, 17), (30, 3, 1, 60);
INSERT INTO efforts VALUES
    (100, 10, 1, 8, 60.0, NULL, NULL, NULL, NULL),
    (101, 10, 2, 6, 70.0, NULL, NULL, 8, 'grindy'),
    (110, 11, 1, NULL, NULL, 50.0, NULL, NULL, NULL),
    (200, 20, 1, 12, 50.0, NULL, NULL, NULL, NULL),
    (210, 21, 1, 8, NULL, NULL, NULL, NULL, NULL),
    (300, 30, 1, NULL, NULL, 3600.0, 1200.0, NULL, NULL);
INSERT INTO body_metrics VALUES (1, '2026-07-08 10:16:29', 'weight_kg', 64.25, 'kg');
"""


@pytest.fixture
def far_east_timezone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run with local time at UTC+14, so code that leaks local time fails on any host."""
    monkeypatch.setenv("TZ", "Etc/GMT-14")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def v1_path(tmp_path: Path) -> Path:
    """A small v1 gym database on disk."""
    path = tmp_path / "v1.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(V1_SCHEMA + V1_ROWS)
    return path


@pytest.fixture
def v1(v1_path: Path) -> Iterator[sqlite3.Connection]:
    """An open connection to the v1 fixture."""
    with closing(sqlite3.connect(v1_path)) as conn:
        yield conn


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated, empty trainer database."""
    with closing(connect(tmp_path / "trainer.db")) as conn:
        migrate(conn)
        yield conn
