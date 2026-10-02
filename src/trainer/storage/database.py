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
    """
    -- The owner's details: one row. Body weight counts towards the volume of
    -- bodyweight exercises.
    CREATE TABLE profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        bodyweight_kg REAL CHECK (bodyweight_kg > 0)
    ) STRICT;
    """,
    """
    -- "No equipment" was a second name for bodyweight: every exercise now has
    -- equipment, and one without any is a bodyweight exercise.
    UPDATE exercises SET equipment = 'bodyweight' WHERE equipment IS NULL;
    """,
    """
    -- The coach's one durable Hermes session: the Coach tab is one conversation.
    CREATE TABLE coach (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        session_id TEXT NOT NULL CHECK (session_id <> '')
    ) STRICT;
    """,
    """
    -- Programs (D4, D7): training weeks then a deload week, the same days every
    -- week. A day is blocks in order; a block of more than one exercise is a
    -- superset. At most one program is proposed (by the coach, awaiting the
    -- owner) and one active at a time; replaced ones are archived.
    CREATE TABLE programs (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK (name <> ''),
        notes TEXT,
        training_weeks INTEGER NOT NULL CHECK (training_weeks >= 1),
        status TEXT NOT NULL CHECK (status IN ('proposed', 'active', 'archived')),
        created_at TEXT NOT NULL,
        started_at TEXT
    ) STRICT;
    CREATE UNIQUE INDEX programs_one_per_status ON programs (status)
        WHERE status IN ('proposed', 'active');

    CREATE TABLE program_days (
        id INTEGER PRIMARY KEY,
        program_id INTEGER NOT NULL REFERENCES programs (id) ON DELETE CASCADE,
        position INTEGER NOT NULL CHECK (position >= 1),
        name TEXT NOT NULL CHECK (name <> ''),
        UNIQUE (program_id, position)
    ) STRICT;

    CREATE TABLE program_blocks (
        id INTEGER PRIMARY KEY,
        day_id INTEGER NOT NULL REFERENCES program_days (id) ON DELETE CASCADE,
        position INTEGER NOT NULL CHECK (position >= 1),
        rest_s INTEGER NOT NULL CHECK (rest_s BETWEEN 0 AND 600),
        UNIQUE (day_id, position)
    ) STRICT;

    -- The range is reps, or seconds for a timed exercise.
    CREATE TABLE block_exercises (
        id INTEGER PRIMARY KEY,
        block_id INTEGER NOT NULL REFERENCES program_blocks (id) ON DELETE CASCADE,
        position INTEGER NOT NULL CHECK (position >= 1),
        exercise_id INTEGER NOT NULL REFERENCES exercises (id),
        sets INTEGER NOT NULL CHECK (sets BETWEEN 1 AND 10),
        rep_min INTEGER NOT NULL CHECK (rep_min >= 1),
        rep_max INTEGER NOT NULL CHECK (rep_max >= rep_min),
        start_load_kg REAL CHECK (start_load_kg >= 0),
        notes TEXT,
        UNIQUE (block_id, position)
    ) STRICT;
    CREATE INDEX block_exercises_exercise ON block_exercises (exercise_id);

    -- An exercise's own load step, when its equipment's default does not fit.
    ALTER TABLE exercises ADD COLUMN load_increment_kg REAL CHECK (load_increment_kg > 0);

    -- A workout trained from a program records which day and week it was; a set
    -- records the program exercise it was for, so supersets keep their shape.
    ALTER TABLE workouts ADD COLUMN program_day_id INTEGER REFERENCES program_days (id);
    ALTER TABLE workouts ADD COLUMN program_week INTEGER
        CHECK (program_week >= 1 AND (program_week IS NULL) = (program_day_id IS NULL));
    CREATE INDEX workouts_program_day ON workouts (program_day_id);
    ALTER TABLE workout_sets ADD COLUMN block_exercise_id INTEGER
        REFERENCES block_exercises (id);
    CREATE INDEX workout_sets_block_exercise ON workout_sets (block_exercise_id);
    """,
    """
    -- Web Push (D1): each browser that turned notifications on, by the push
    -- service address it gave, with the keys its pushes are encrypted for.
    CREATE TABLE push_subscriptions (
        id INTEGER PRIMARY KEY,
        endpoint TEXT NOT NULL UNIQUE CHECK (endpoint LIKE 'https://%'),
        p256dh TEXT NOT NULL CHECK (p256dh <> ''),
        auth TEXT NOT NULL CHECK (auth <> ''),
        created_at TEXT NOT NULL
    ) STRICT;

    -- What the app told the owner, kept whether or not a push reached a phone.
    -- A notice shows from due_at; until then the app may claim it as seen, and
    -- then it is never pushed. sent_at is when its push was dealt with.
    CREATE TABLE inbox (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('coach', 'proposal', 'test')),
        title TEXT NOT NULL CHECK (title <> ''),
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        due_at TEXT NOT NULL CHECK (due_at >= created_at),
        sent_at TEXT,
        read_at TEXT
    ) STRICT;
    CREATE INDEX inbox_due_at ON inbox (due_at);
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
