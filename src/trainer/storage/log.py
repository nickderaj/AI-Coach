"""The training log: workouts and their sets, body metrics and cardio."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True)
class WorkoutRecord:
    """A workout; times are UTC ISO-8601 strings."""

    started_at: str
    ended_at: str | None
    notes: str | None
    source: str


@dataclass(frozen=True)
class SetRecord:
    """One set: which exercise, where it sits in the workout, and what was done."""

    workout_id: int
    exercise_id: int
    exercise_position: int
    set_number: int
    reps: int | None = None
    load_kg: float | None = None
    duration_s: float | None = None
    rpe: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class BodyMetricRecord:
    """A body measurement such as weight."""

    measured_at: str
    metric: str
    value: float
    unit: str
    source: str


@dataclass(frozen=True)
class CardioRecord:
    """A cardio session."""

    started_at: str
    activity: str
    duration_s: float | None
    distance_m: float | None
    notes: str | None
    source: str


def delete_source(conn: sqlite3.Connection, source: str) -> None:
    """Remove everything previously written by ``source`` (sets cascade with workouts)."""
    conn.execute("""DELETE FROM workouts WHERE source = ?""", (source,))
    conn.execute("""DELETE FROM body_metrics WHERE source = ?""", (source,))
    conn.execute("""DELETE FROM cardio_sessions WHERE source = ?""", (source,))


def insert_workout(conn: sqlite3.Connection, workout: WorkoutRecord) -> int:
    """Insert a workout and return its id."""
    row = conn.execute(
        """
        INSERT INTO workouts (started_at, ended_at, notes, source) VALUES (?, ?, ?, ?)
        RETURNING id
        """,
        (workout.started_at, workout.ended_at, workout.notes, workout.source),
    ).fetchone()
    workout_id: int = row[0]
    return workout_id


def insert_set(conn: sqlite3.Connection, record: SetRecord) -> None:
    """Insert one set."""
    conn.execute(
        """
        INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number,
            reps, load_kg, duration_s, rpe, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.workout_id,
            record.exercise_id,
            record.exercise_position,
            record.set_number,
            record.reps,
            record.load_kg,
            record.duration_s,
            record.rpe,
            record.notes,
        ),
    )


def insert_body_metric(conn: sqlite3.Connection, record: BodyMetricRecord) -> None:
    """Insert one body measurement."""
    conn.execute(
        """
        INSERT INTO body_metrics (measured_at, metric, value, unit, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        (record.measured_at, record.metric, record.value, record.unit, record.source),
    )


def insert_cardio(conn: sqlite3.Connection, record: CardioRecord) -> None:
    """Insert one cardio session."""
    conn.execute(
        """
        INSERT INTO cardio_sessions (started_at, activity, duration_s, distance_m, notes, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record.started_at,
            record.activity,
            record.duration_s,
            record.distance_m,
            record.notes,
            record.source,
        ),
    )
