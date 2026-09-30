"""Read models for browsing the training log."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import groupby
from typing import TYPE_CHECKING, Any

from trainer.domain.exercises import Measure
from trainer.domain.records import set_rank, set_volume

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence


@dataclass(frozen=True)
class SetView:
    """One set as performed."""

    set_number: int
    reps: int | None
    load_kg: float | None
    duration_s: float | None
    rpe: int | None
    notes: str | None
    client_id: str | None


@dataclass(frozen=True)
class ExerciseLine:
    """One exercise in a workout summary: how many sets, and the best of them."""

    position: int
    name: str
    measure: Measure
    sets: int
    best: SetView


@dataclass(frozen=True)
class WorkoutSummary:
    """A workout in a list: when, what was trained, and how much."""

    id: int
    started_at: str
    ended_at: str | None
    exercises: list[ExerciseLine]
    set_count: int
    volume_kg: float


@dataclass(frozen=True)
class ExerciseBlock:
    """One exercise within a workout, with its sets in order."""

    position: int
    exercise_id: int
    name: str
    measure: Measure
    sets: list[SetView]


@dataclass(frozen=True)
class WorkoutDetail:
    """A whole workout."""

    id: int
    started_at: str
    ended_at: str | None
    notes: str | None
    client_id: str | None
    exercises: list[ExerciseBlock]


@dataclass(frozen=True)
class ExerciseSummary:
    """A catalogue entry with how it has been trained."""

    id: int
    name: str
    equipment: str | None
    muscle_groups: str | None
    measure: Measure
    workouts: int
    last_done: str | None
    best_load_kg: float | None


@dataclass(frozen=True)
class ExerciseSession:
    """One block of an exercise in a workout: the workout and position identify it.

    An exercise done twice in a workout (say, at the start and again at the end)
    is two sessions with the same ``workout_id`` and different ``position``.
    """

    workout_id: int
    position: int
    started_at: str
    sets: list[SetView]


@dataclass(frozen=True)
class ExerciseHistory:
    """An exercise and its sessions, newest first."""

    exercise: ExerciseSummary
    sessions: list[ExerciseSession]


# Rows are unpacked by position (sqlite3.Row name lookups are case-insensitive, so
# name strings invite unkillable mutants); each SELECT lists columns in field order.


def _set(row: Sequence[Any]) -> SetView:
    """``row`` ends with: set_number, reps, load_kg, duration_s, rpe, notes, client_id."""
    return SetView(*row[-7:])


def list_workouts(conn: sqlite3.Connection, limit: int) -> list[WorkoutSummary]:
    """The ``limit`` most recent workouts, newest first."""
    workouts = conn.execute(
        """
        SELECT id FROM workouts
        ORDER BY started_at DESC, id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_summary_of(get_workout(conn, workout[0])) for workout in workouts]


def _best(block: ExerciseBlock) -> SetView:
    return max(
        block.sets,
        key=lambda s: set_rank(block.measure, s.reps, s.load_kg, s.duration_s),
    )


def _summary_of(detail: WorkoutDetail) -> WorkoutSummary:
    """Summarise a workout from its full detail (one source of truth for both)."""
    sets = [set_view for block in detail.exercises for set_view in block.sets]
    return WorkoutSummary(
        id=detail.id,
        started_at=detail.started_at,
        ended_at=detail.ended_at,
        exercises=[
            ExerciseLine(block.position, block.name, block.measure, len(block.sets), _best(block))
            for block in detail.exercises
        ],
        set_count=len(sets),
        volume_kg=sum(set_volume(s.reps, s.load_kg) for s in sets),
    )


class WorkoutNotFoundError(LookupError):
    """No workout has the requested id."""


def get_workout(conn: sqlite3.Connection, workout_id: int) -> WorkoutDetail:
    """One workout with every set.

    Raises:
        WorkoutNotFoundError: if there is no such workout.
    """
    workout = conn.execute(
        """SELECT id, started_at, ended_at, notes, client_id FROM workouts WHERE id = ?""",
        (workout_id,),
    ).fetchone()
    if workout is None:
        message = f"no workout {workout_id}"
        raise WorkoutNotFoundError(message)
    rows = conn.execute(
        """
        SELECT s.exercise_position, s.exercise_id, e.display_name, e.measure, s.set_number,
            s.reps, s.load_kg, s.duration_s, s.rpe, s.notes, s.client_id
        FROM workout_sets s JOIN exercises e ON e.id = s.exercise_id
        WHERE s.workout_id = ? ORDER BY s.exercise_position, s.set_number
        """,
        (workout_id,),
    ).fetchall()
    blocks = [_block(list(group)) for _, group in groupby(rows, key=lambda row: row[0])]
    found_id, started_at, ended_at, notes, client_id = workout
    return WorkoutDetail(found_id, started_at, ended_at, notes, client_id, blocks)


def current_workout(conn: sqlite3.Connection) -> WorkoutDetail | None:
    """The most recently started app workout that has not been finished, if any."""
    row = conn.execute(
        """
        SELECT id FROM workouts WHERE client_id IS NOT NULL AND ended_at IS NULL
        ORDER BY started_at DESC, id DESC LIMIT 1
        """
    ).fetchone()
    return None if row is None else get_workout(conn, row[0])


def _block(rows: list[sqlite3.Row]) -> ExerciseBlock:
    """``rows`` start with: exercise_position, exercise_id, display_name, measure."""
    position, exercise_id, name, measure = rows[0][:4]
    return ExerciseBlock(position, exercise_id, name, Measure(measure), [_set(r) for r in rows])


_SUMMARY_SQL = """
    SELECT e.id, e.display_name, e.equipment, e.muscle_groups, e.measure,
        count(DISTINCT s.workout_id) AS workouts, max(w.started_at) AS last_done,
        max(s.load_kg) AS best_load_kg
    FROM exercises e
    LEFT JOIN workout_sets s ON s.exercise_id = e.id
    LEFT JOIN workouts w ON w.id = s.workout_id
"""


def _summary(row: sqlite3.Row) -> ExerciseSummary:
    """``row`` follows the column order of ``_SUMMARY_SQL``."""
    exercise_id, name, equipment, muscle_groups, measure, workouts, last_done, best = row
    return ExerciseSummary(
        exercise_id, name, equipment, muscle_groups, Measure(measure), workouts, last_done, best
    )


def list_exercises(conn: sqlite3.Connection) -> list[ExerciseSummary]:
    """The whole catalogue, most recently trained first, never-trained last by name."""
    rows = conn.execute(
        _SUMMARY_SQL
        + """
        GROUP BY e.id
        ORDER BY last_done IS NULL, last_done DESC, e.display_name
        """
    ).fetchall()
    return [_summary(row) for row in rows]


def exercise_history(conn: sqlite3.Connection, exercise_id: int) -> ExerciseHistory | None:
    """One exercise and every session it was trained in, or ``None``."""
    row = conn.execute(
        _SUMMARY_SQL + """ WHERE e.id = ? GROUP BY e.id""", (exercise_id,)
    ).fetchone()
    if row is None:
        return None
    rows = conn.execute(
        """
        SELECT w.id, s.exercise_position, w.started_at, s.set_number, s.reps, s.load_kg,
            s.duration_s, s.rpe, s.notes, s.client_id
        FROM workout_sets s JOIN workouts w ON w.id = s.workout_id
        WHERE s.exercise_id = ?
        ORDER BY w.started_at DESC, w.id DESC, s.exercise_position, s.set_number
        """,
        (exercise_id,),
    ).fetchall()
    sessions = [_session(list(block)) for _, block in groupby(rows, key=lambda r: (r[0], r[1]))]
    return ExerciseHistory(_summary(row), sessions)


def _session(rows: list[sqlite3.Row]) -> ExerciseSession:
    """``rows`` start with: workout id, exercise_position, started_at."""
    workout_id, position, started_at = rows[0][:3]
    return ExerciseSession(workout_id, position, started_at, [_set(r) for r in rows])
