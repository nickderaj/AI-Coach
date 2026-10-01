"""Logging training from the app: workouts, sets and new exercises."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trainer.domain.exercises import Equipment, Measure, near_duplicates, normalise_name
from trainer.domain.times import utc_iso
from trainer.storage.catalogue import ExerciseSpec, create_exercise, known_names, resolve
from trainer.storage.database import write_transaction
from trainer.storage.history import (
    ExerciseSummary,
    WorkoutDetail,
    exercise_history,
    get_workout,
)
from trainer.storage.journal import (
    ProgramLink,
    SetValues,
    delete_set,
    delete_workout,
    save_set,
    save_workout,
    workout_id_for,
    workout_link,
)
from trainer.storage.programs import (
    day_claimed,
    day_program,
    other_program_workout_in_progress,
    set_days,
    slot_place,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime


class NotFoundError(LookupError):
    """A referenced workout or exercise does not exist."""


class InvalidWorkoutError(ValueError):
    """A workout's times, or its program day and week, are inconsistent."""


class StaleProgramDayError(ValueError):
    """A workout would train a program day that is done, or a program no longer active."""


class InvalidSetError(ValueError):
    """A set's program exercise does not fit its workout or exercise."""


class DuplicateExerciseError(Exception):
    """A new exercise would duplicate, or probably duplicates, existing ones.

    A plain class, not a frozen dataclass: Python assigns ``__traceback__`` to
    exceptions as they propagate (e.g. through a context manager).
    """

    def __init__(self, *, exact: bool, matches: list[ExerciseSummary]) -> None:
        """Record whether the match is exact and which exercises matched."""
        super().__init__("exists" if exact else "similar")
        self.exact = exact
        self.matches = matches


@dataclass(frozen=True)
class NewExercise:
    """An exercise the owner wants to add to the catalogue."""

    name: str
    equipment: Equipment
    muscle_groups: str | None
    measure: Measure


def record_workout(
    conn: sqlite3.Connection,
    client_id: str,
    times: tuple[datetime, datetime | None],
    notes: str | None,
    program: ProgramLink | None = None,
) -> WorkoutDetail:
    """Start, update or finish the app workout ``client_id``.

    ``program`` is the program day and week it trains, if any. Once it has
    sets for that day's program exercises, it keeps that day (in any week).

    Raises:
        InvalidWorkoutError: if it ends before it starts, the program day does
            not exist or has no such week, or the workout has program sets for
            another day than ``program``'s.
        StaleProgramDayError: if a workout newly names a day another workout
            already trains that week (done or in progress), a day of a program
            no longer active (a plan seen before it changed), or any program
            day while another program workout is unfinished.
    """
    started, ended = times
    if ended is not None and ended < started:
        message = "a workout cannot end before it starts"
        raise InvalidWorkoutError(message)
    stored = (utc_iso(started), None if ended is None else utc_iso(ended))
    with write_transaction(conn):
        if program is not None:
            _check_link(conn, client_id, program)
        if set_days(conn, client_id) - {None if program is None else program.day_id}:
            message = "the workout has sets for another program day"
            raise InvalidWorkoutError(message)
        workout_id = save_workout(conn, client_id, stored, notes, program)
    return get_workout(conn, workout_id)


def _check_link(conn: sqlite3.Connection, client_id: str, program: ProgramLink) -> None:
    day = day_program(conn, program.day_id)
    if day is None:
        message = "program day not found"
        raise InvalidWorkoutError(message)
    if program.week > day.weeks:
        message = f"the program has {day.weeks} weeks"
        raise InvalidWorkoutError(message)
    if workout_link(conn, client_id) == program:
        return  # its start again, or its finish: accepted when it was started
    if not day.active:
        message = "that program is no longer active"
        raise StaleProgramDayError(message)
    # Done, or begun on another phone (one may have started it offline). This
    # workout's own claim returned above, as an unchanged link.
    if day_claimed(conn, program.day_id, program.week):
        message = f"week {program.week} of day {program.day_id} already has a workout"
        raise StaleProgramDayError(message)
    # One program workout at a time: another phone's, or one of a program
    # replaced before that was refused, is finished or discarded first.
    if other_program_workout_in_progress(conn, client_id):
        message = "finish or discard the workout in progress first"
        raise StaleProgramDayError(message)


def remove_workout(conn: sqlite3.Connection, client_id: str) -> None:
    """Delete an app workout and its sets (no-op if already gone)."""
    with write_transaction(conn):
        delete_workout(conn, client_id)


def record_set(
    conn: sqlite3.Connection,
    client_id: str,
    placement: tuple[str, int],
    values: SetValues,
    slot: int | None = None,
) -> WorkoutDetail:
    """Log or correct set ``client_id``; ``placement`` is (workout client id, exercise id).

    ``slot`` is the program exercise the set is for, if any: one of the
    workout's program day, for the same exercise.

    Returns:
        The whole workout after the change.

    Raises:
        NotFoundError: if the workout or the exercise does not exist.
        InvalidSetError: if ``slot`` is not on the workout's program day, or
            is for another exercise.
    """
    workout_client_id, exercise_id = placement
    # Lookups, slot allocation and the write share one locked transaction, so
    # concurrent requests (say, an offline replay racing a live tap) queue.
    with write_transaction(conn):
        workout_id = workout_id_for(conn, workout_client_id)
        if workout_id is None:
            message = "workout not found"
            raise NotFoundError(message)
        if exercise_history(conn, exercise_id) is None:
            message = "exercise not found"
            raise NotFoundError(message)
        if slot is not None:
            _check_slot(conn, get_workout(conn, workout_id), exercise_id, slot)
        save_set(conn, client_id, (workout_id, exercise_id, slot), values)
    return get_workout(conn, workout_id)


def _check_slot(
    conn: sqlite3.Connection, workout: WorkoutDetail, exercise_id: int, slot: int
) -> None:
    place = slot_place(conn, slot)
    if place is None or place.day_id != workout.program_day_id:
        message = "the program exercise is not on this workout's program day"
        raise InvalidSetError(message)
    if place.exercise_id != exercise_id:
        message = "the program exercise is for another exercise"
        raise InvalidSetError(message)


def remove_set(conn: sqlite3.Connection, client_id: str) -> None:
    """Delete a logged set (no-op if already gone)."""
    with write_transaction(conn):
        delete_set(conn, client_id)


def _summaries(conn: sqlite3.Connection, ids: list[int]) -> list[ExerciseSummary]:
    return [
        history.exercise
        for history in (exercise_history(conn, exercise_id) for exercise_id in ids)
        if history is not None
    ]


def spec_for(exercise: NewExercise) -> ExerciseSpec:
    """How a new exercise is stored: keyed by its normalised name."""
    return ExerciseSpec(
        name=normalise_name(exercise.name),
        display_name=" ".join(exercise.name.split()),
        equipment=exercise.equipment.value,
        muscle_groups=exercise.muscle_groups,
        measure=exercise.measure,
    )


def add_exercise(
    conn: sqlite3.Connection, exercise: NewExercise, *, allow_similar: bool
) -> ExerciseSummary:
    """Add an exercise to the catalogue.

    Raises:
        DuplicateExerciseError: if the name (or an alias) is taken, or, unless
            ``allow_similar``, if it probably duplicates existing exercises.
    """
    spec = spec_for(exercise)
    # The duplicate checks and the insert share one locked transaction, so two
    # concurrent requests cannot both pass the checks and race to insert.
    with write_transaction(conn):
        taken = resolve(conn, exercise.name)
        if taken is not None:
            raise DuplicateExerciseError(exact=True, matches=_summaries(conn, [taken]))
        similar = near_duplicates(exercise.name, known_names(conn))
        if similar and not allow_similar:
            raise DuplicateExerciseError(exact=False, matches=_summaries(conn, similar))
        exercise_id = create_exercise(conn, spec)
    return _summaries(conn, [exercise_id])[0]
