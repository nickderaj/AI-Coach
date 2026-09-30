"""Open the database and bring its schema up to date."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

DATABASE_FILE = "trainer.db"

# SQL is written in triple-quoted strings throughout storage: SQL keywords and
# identifiers are case-insensitive, and mutmut leaves triple-quoted strings alone,
# so it does not generate unkillable upper/lower-case mutants of every query.

# Append-only: each entry upgrades the schema by one version (PRAGMA user_version).
# Never edit a released migration; add a new one.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE exercises (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        equipment TEXT,
        muscle_groups TEXT,
        measure TEXT NOT NULL CHECK (measure IN ('reps', 'seconds', 'distance'))
    ) STRICT;

    CREATE TABLE exercise_aliases (
        alias TEXT PRIMARY KEY,
        exercise_id INTEGER NOT NULL REFERENCES exercises (id) ON DELETE CASCADE
    ) STRICT;

    CREATE TABLE workouts (
        id INTEGER PRIMARY KEY,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        notes TEXT,
        source TEXT NOT NULL
    ) STRICT;
    CREATE INDEX workouts_started_at ON workouts (started_at);

    CREATE TABLE workout_sets (
        id INTEGER PRIMARY KEY,
        workout_id INTEGER NOT NULL REFERENCES workouts (id) ON DELETE CASCADE,
        exercise_id INTEGER NOT NULL REFERENCES exercises (id),
        exercise_position INTEGER NOT NULL CHECK (exercise_position >= 1),
        set_number INTEGER NOT NULL CHECK (set_number >= 1),
        reps INTEGER CHECK (reps >= 0),
        load_kg REAL CHECK (load_kg >= 0),
        duration_s REAL CHECK (duration_s >= 0),
        rpe INTEGER CHECK (rpe BETWEEN 1 AND 10),
        notes TEXT,
        client_id TEXT UNIQUE,
        UNIQUE (workout_id, exercise_position, set_number)
    ) STRICT;
    CREATE INDEX workout_sets_exercise ON workout_sets (exercise_id);

    CREATE TABLE body_metrics (
        id INTEGER PRIMARY KEY,
        measured_at TEXT NOT NULL,
        metric TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT NOT NULL,
        source TEXT NOT NULL
    ) STRICT;

    CREATE TABLE cardio_sessions (
        id INTEGER PRIMARY KEY,
        started_at TEXT NOT NULL,
        activity TEXT NOT NULL,
        duration_s REAL CHECK (duration_s >= 0),
        distance_m REAL CHECK (distance_m >= 0),
        notes TEXT,
        source TEXT NOT NULL
    ) STRICT;
    """,
    """
    -- Workouts logged in the app carry the phone-generated id they were created
    -- under, so offline replays update rather than duplicate them.
    ALTER TABLE workouts ADD COLUMN client_id TEXT;
    CREATE UNIQUE INDEX workouts_client_id ON workouts (client_id);
    """,
)


class SchemaError(RuntimeError):
    """The database was written by a newer version of this app."""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open ``path`` with foreign keys enforced, WAL journaling and a busy timeout."""
    conn = sqlite3.connect(path)  # the default 5 s timeout doubles as the busy timeout
    conn.row_factory = sqlite3.Row
    conn.execute("""PRAGMA foreign_keys = ON""")
    conn.execute("""PRAGMA journal_mode = WAL""")
    return conn


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Run a read-modify-write atomically: take the write lock before reading.

    ``BEGIN IMMEDIATE`` makes concurrent writers queue (up to the busy timeout)
    instead of two of them reading the same state and both acting on it.
    Commits on success, rolls back on any exception.
    """
    conn.execute("""BEGIN IMMEDIATE""")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open an existing database strictly read-only.

    A ``mode=ro`` URI makes SQLite itself refuse every write and never create the
    file; unlike :func:`connect`, no setting (in particular the journal mode) is
    changed on it, so the file is left byte-for-byte untouched.
    """
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    # SQLite builds with SQLITE_USE_URI (e.g. Debian) treat file: names as URIs even
    # why: with uri=False, so a mutant dropping the flag is undetectable on such hosts.
    conn = sqlite3.connect(uri, uri=True)  # pragma: no mutate
    conn.row_factory = sqlite3.Row
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    """The schema version recorded in the database."""
    version: int = conn.execute("""PRAGMA user_version""").fetchone()[0]
    return version


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations, each atomically; return the resulting version.

    Raises:
        SchemaError: if the database is newer than this code.
    """
    current = schema_version(conn)
    if current > len(MIGRATIONS):
        message = f"database schema v{current} is newer than this app (v{len(MIGRATIONS)})"
        raise SchemaError(message)
    for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise
    return schema_version(conn)
