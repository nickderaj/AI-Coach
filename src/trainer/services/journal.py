"""Logging training from the app: workouts, sets and new exercises."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trainer.domain.exercises import Equipment, Measure, near_duplicates, normalise_name
from trainer.domain.times import utc_iso
from trainer.storage.catalogue import ExerciseSpec, create_exercise, known_names, resolve
from trainer.storage.history import (
    ExerciseSummary,
    WorkoutDetail,
    exercise_history,
    get_workout,
)
from trainer.storage.journal import (
    SetValues,
    delete_set,
    delete_workout,
    save_set,
    save_workout,
    workout_id_for,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime


class NotFoundError(LookupError):
    """A referenced workout or exercise does not exist."""


class InvalidWorkoutError(ValueError):
    """A workout's times are inconsistent."""


@dataclass(frozen=True)
class DuplicateExerciseError(Exception):
    """A new exercise would duplicate, or probably duplicates, existing ones."""

    exact: bool
    matches: list[ExerciseSummary]


@dataclass(frozen=True)
class NewExercise:
    """An exercise the owner wants to add to the catalogue."""

    name: str
    equipment: Equipment | None
    muscle_groups: str | None
    measure: Measure


def record_workout(
    conn: sqlite3.Connection,
    client_id: str,
    times: tuple[datetime, datetime | None],
    notes: str | None,
) -> WorkoutDetail:
    """Start, update or finish the app workout ``client_id``.

    Raises:
        InvalidWorkoutError: if it ends before it starts.
    """
    started, ended = times
    if ended is not None and ended < started:
        message = "a workout cannot end before it starts"
        raise InvalidWorkoutError(message)
    with conn:
        workout_id = save_workout(
            conn, client_id, (utc_iso(started), None if ended is None else utc_iso(ended)), notes
        )
    return get_workout(conn, workout_id)


def remove_workout(conn: sqlite3.Connection, client_id: str) -> None:
    """Delete an app workout and its sets (no-op if already gone)."""
    with conn:
        delete_workout(conn, client_id)


def record_set(
    conn: sqlite3.Connection,
    client_id: str,
    placement: tuple[str, int],
    values: SetValues,
) -> WorkoutDetail:
    """Log or correct set ``client_id``; ``placement`` is (workout client id, exercise id).

    Returns:
        The whole workout after the change.

    Raises:
        NotFoundError: if the workout or the exercise does not exist.
    """
    workout_client_id, exercise_id = placement
    workout_id = workout_id_for(conn, workout_client_id)
    if workout_id is None:
        message = "workout not found"
        raise NotFoundError(message)
    if exercise_history(conn, exercise_id) is None:
        message = "exercise not found"
        raise NotFoundError(message)
    with conn:
        save_set(conn, client_id, (workout_id, exercise_id), values)
    return get_workout(conn, workout_id)


def remove_set(conn: sqlite3.Connection, client_id: str) -> None:
    """Delete a logged set (no-op if already gone)."""
    with conn:
        delete_set(conn, client_id)


def _summaries(conn: sqlite3.Connection, ids: list[int]) -> list[ExerciseSummary]:
    return [
        history.exercise
        for history in (exercise_history(conn, exercise_id) for exercise_id in ids)
        if history is not None
    ]


def add_exercise(
    conn: sqlite3.Connection, exercise: NewExercise, *, allow_similar: bool
) -> ExerciseSummary:
    """Add an exercise to the catalogue.

    Raises:
        DuplicateExerciseError: if the name (or an alias) is taken, or, unless
            ``allow_similar``, if it probably duplicates existing exercises.
    """
    taken = resolve(conn, exercise.name)
    if taken is not None:
        raise DuplicateExerciseError(exact=True, matches=_summaries(conn, [taken]))
    similar = near_duplicates(exercise.name, known_names(conn))
    if similar and not allow_similar:
        raise DuplicateExerciseError(exact=False, matches=_summaries(conn, similar))
    spec = ExerciseSpec(
        name=normalise_name(exercise.name),
        display_name=" ".join(exercise.name.split()),
        equipment=None if exercise.equipment is None else exercise.equipment.value,
        muscle_groups=exercise.muscle_groups,
        measure=exercise.measure,
    )
    with conn:
        exercise_id = create_exercise(conn, spec)
    return _summaries(conn, [exercise_id])[0]
