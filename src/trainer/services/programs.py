"""Programs: the coach's proposals, the active block, and what today holds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from trainer.domain.exercises import Measure
from trainer.domain.programs import (
    TRAINING_WEEKS,
    Position,
    Prescription,
    SetDone,
    Target,
    is_deload_week,
    next_position,
    target_for,
)
from trainer.domain.records import carried_load
from trainer.domain.times import utc_iso
from trainer.storage.database import write_transaction
from trainer.storage.history import (
    ExerciseSession,
    WorkoutDetail,
    current_workout,
    last_session,
    list_exercises,
)
from trainer.storage.profile import read_profile
from trainer.storage.programs import (
    BlockSpec,
    DaySpec,
    Program,
    ProgramExercise,
    ProgramSpec,
    ProgramStatus,
    SlotSet,
    SlotSpec,
    activate_program,
    archive_program,
    get_program,
    insert_program,
    last_position,
    last_slot_sets,
    program_in_progress,
    program_with_status,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

# SQLite's INTEGER is signed 64-bit; a larger id would overflow in the query.
MAX_ROW_ID = 2**63 - 1
# A plain alias, not a `type` statement, so a schema shows the bounds inline.
RowId = Annotated[int, Field(ge=1, le=MAX_ROW_ID)]

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SlotIn(_Shape):
    """One exercise of a block."""

    exercise_id: Annotated[RowId, Field(description="An exercise id from the catalogue.")]
    sets: Annotated[int, Field(ge=1, le=10, description="Working sets.")]
    rep_min: Annotated[
        int,
        Field(ge=1, le=600, description="Bottom of the range: reps, or seconds if timed."),
    ]
    rep_max: Annotated[
        int,
        Field(
            ge=1,
            le=600,
            description="Top of the range. Reaching it on every set adds load next time.",
        ),
    ]
    start_load_kg: (
        Annotated[
            float,
            Field(
                ge=0,
                le=1000,
                description=(
                    "Load for the first session in kg: per dumbbell, or added to body weight. "
                    "Leave out to let the owner choose."
                ),
            ),
        ]
        | None
    ) = None
    notes: Annotated[Text, StringConstraints(max_length=200)] | None = None

    @model_validator(mode="after")
    def range_in_order(self) -> Self:
        """The top of the range is not below its bottom."""
        if self.rep_max < self.rep_min:
            message = "rep_max is below rep_min"
            raise ValueError(message)
        return self


class BlockIn(_Shape):
    """A block: one exercise, or a superset of two or three."""

    rest_s: Annotated[
        int, Field(ge=0, le=600, description="Rest after each set or round, in seconds.")
    ] = 90
    exercises: Annotated[
        list[SlotIn],
        Field(
            min_length=1,
            max_length=3,
            description="One exercise, or two or three done as a superset (A1, A2...).",
        ),
    ]


class DayIn(_Shape):
    """A day of the program, repeated every week."""

    name: Annotated[Text, StringConstraints(max_length=40)]
    blocks: Annotated[list[BlockIn], Field(min_length=1, max_length=12)]


class ProgramIn(_Shape):
    """A program: its days, trained in order every week for six weeks, then a deload week."""

    name: Annotated[Text, StringConstraints(max_length=60)]
    notes: Annotated[Text, StringConstraints(max_length=2000)] | None = None
    days: Annotated[list[DayIn], Field(min_length=1, max_length=7)]


class ProgramError(ValueError):
    """A program names exercises that cannot be in it."""


class NoProposalError(LookupError):
    """There is no such proposed program."""


class ProgramInUseError(RuntimeError):
    """The active program has a workout in progress, so it cannot be replaced yet."""


def _spec(program: ProgramIn) -> ProgramSpec:
    return ProgramSpec(
        program.name,
        program.notes,
        TRAINING_WEEKS,
        tuple(
            DaySpec(
                day.name,
                tuple(
                    BlockSpec(
                        block.rest_s,
                        tuple(
                            SlotSpec(
                                slot.exercise_id,
                                slot.sets,
                                slot.rep_min,
                                slot.rep_max,
                                slot.start_load_kg,
                                slot.notes,
                            )
                            for slot in block.exercises
                        ),
                    )
                    for block in day.blocks
                ),
            )
            for day in program.days
        ),
    )


def _check_exercises(conn: sqlite3.Connection, program: ProgramIn) -> None:
    measures = {exercise.id: exercise.measure for exercise in list_exercises(conn)}
    wanted = {
        slot.exercise_id for day in program.days for block in day.blocks for slot in block.exercises
    }
    unknown = sorted(wanted - measures.keys())
    if unknown:
        message = f"no exercise has id {', '.join(map(str, unknown))}"
        raise ProgramError(message)
    distance = sorted(id_ for id_ in wanted if measures[id_] is Measure.DISTANCE)
    if distance:
        message = f"exercise {', '.join(map(str, distance))} is measured in distance"
        raise ProgramError(message)


def propose_program(conn: sqlite3.Connection, program: ProgramIn, now: datetime) -> Program:
    """Save ``program`` as the proposal; any earlier one is archived.

    Raises:
        ProgramError: if an exercise does not exist or is measured in distance.
    """
    with write_transaction(conn):
        _check_exercises(conn, program)
        earlier = program_with_status(conn, ProgramStatus.PROPOSED)
        if earlier is not None:
            archive_program(conn, earlier)
        program_id = insert_program(conn, _spec(program), ProgramStatus.PROPOSED, utc_iso(now))
    return get_program(conn, program_id)


def decline_proposal(conn: sqlite3.Connection, program_id: int) -> None:
    """Turn down the proposed program ``program_id``: it is archived.

    Raises:
        NoProposalError: if ``program_id`` is not the proposed program (one
            the owner has not seen may have replaced it).
    """
    with write_transaction(conn):
        _check_proposal(conn, program_id)
        archive_program(conn, program_id)


def _check_proposal(conn: sqlite3.Connection, program_id: int) -> None:
    if program_with_status(conn, ProgramStatus.PROPOSED) != program_id:
        message = f"program {program_id} is not the proposal"
        raise NoProposalError(message)


def accept_proposal(conn: sqlite3.Connection, program_id: int, now: datetime) -> Program:
    """Start training the proposed program ``program_id``; the active one is archived.

    Raises:
        NoProposalError: if ``program_id`` is not the proposed program.
        ProgramInUseError: if a workout of the active program is in progress:
            replacing the program then would leave that workout without a plan.
    """
    with write_transaction(conn):
        _check_proposal(conn, program_id)
        active = program_with_status(conn, ProgramStatus.ACTIVE)
        if active is not None and program_in_progress(conn, active):
            message = "finish or discard the workout in progress first"
            raise ProgramInUseError(message)
        activate_program(conn, program_id, utc_iso(now))
    return get_program(conn, program_id)


@dataclass(frozen=True)
class Programs:
    """The active and the proposed program, and the active one's next day.

    ``next`` is ``None`` without an active program, or once its block is done.
    """

    active: Program | None
    proposed: Program | None
    next: Position | None


def programs(conn: sqlite3.Connection) -> Programs:
    """The programs the owner can see: what is trained, and what is proposed."""
    active_id = program_with_status(conn, ProgramStatus.ACTIVE)
    proposed_id = program_with_status(conn, ProgramStatus.PROPOSED)
    active = None if active_id is None else get_program(conn, active_id)
    proposed = None if proposed_id is None else get_program(conn, proposed_id)
    following = None if active is None else _position(conn, active, current_workout(conn))
    return Programs(active, proposed, following)


@dataclass(frozen=True)
class PlannedExercise:
    """An exercise of today's day: its prescription, its target and last time."""

    block_exercise_id: int
    exercise_id: int
    name: str
    equipment: str | None
    measure: Measure
    # Share of body weight moved in each rep, on top of the load (bodyweight exercises).
    carried_kg: float
    sets: int
    rep_min: int
    rep_max: int
    notes: str | None
    target: Target
    # The exercise's most recent session outside today's workout, wherever it was.
    last: ExerciseSession | None


@dataclass(frozen=True)
class PlannedBlock:
    """A block of today's day: more than one exercise is a superset."""

    rest_s: int
    exercises: list[PlannedExercise]


@dataclass(frozen=True)
class PlannedDay:
    """Today's program day, in its week."""

    id: int
    position: int
    name: str
    week: int
    deload: bool
    blocks: list[PlannedBlock]


@dataclass(frozen=True)
class Today:
    """What the active program holds next.

    ``day`` is ``None`` once the block is done. ``workout_client_id`` is the
    unfinished workout already training that day, if there is one.
    """

    program_id: int
    program_name: str
    training_weeks: int
    days: int
    day: PlannedDay | None
    workout_client_id: str | None


def today(conn: sqlite3.Connection) -> Today | None:
    """The next day of the active program, planned; ``None`` without an active program."""
    program_id = program_with_status(conn, ProgramStatus.ACTIVE)
    if program_id is None:
        return None
    program = get_program(conn, program_id)
    current = current_workout(conn)
    position = _position(conn, program, current)
    training = current if _in_progress(program, current) else None
    return Today(
        program.id,
        program.name,
        program.training_weeks,
        len(program.days),
        None if position is None else _plan(conn, program, position, current),
        None if training is None else training.client_id,
    )


# coverage-critical
def _in_progress(program: Program, current: WorkoutDetail | None) -> Position | None:
    """The day the unfinished workout ``current`` trains, if it is a day of ``program``."""
    if current is None or current.program_week is None:
        return None
    for day_number, day in enumerate(program.days, start=1):
        if day.id == current.program_day_id:
            return Position(current.program_week, day_number)
    return None


# coverage-critical
def _position(
    conn: sqlite3.Connection, program: Program, current: WorkoutDetail | None
) -> Position | None:
    """The day being trained, if a workout in progress trains one; else the next one."""
    training = _in_progress(program, current)
    if training is not None:
        return training
    done = last_position(conn, program.id)
    return next_position(done, len(program.days), program.training_weeks)


def _plan(
    conn: sqlite3.Connection, program: Program, position: Position, current: WorkoutDetail | None
) -> PlannedDay:
    day = program.days[position.day - 1]
    deload = is_deload_week(position.week, program.training_weeks)
    bodyweight = read_profile(conn).bodyweight_kg
    exclude = None if current is None else current.id
    return PlannedDay(
        day.id,
        position.day,
        day.name,
        position.week,
        deload,
        [
            PlannedBlock(
                block.rest_s,
                [
                    _planned(conn, (exercise, program.training_weeks, deload), bodyweight, exclude)
                    for exercise in block.exercises
                ],
            )
            for block in day.blocks
        ],
    )


def _planned(
    conn: sqlite3.Connection,
    slot: tuple[ProgramExercise, int, bool],
    bodyweight: float | None,
    exclude: int | None,
) -> PlannedExercise:
    """``slot`` is (the program exercise, the program's training weeks, deload week)."""
    exercise, training_weeks, deload = slot
    prescription = Prescription(
        exercise.sets,
        exercise.rep_min,
        exercise.rep_max,
        exercise.start_load_kg,
        exercise.increment_kg,
    )
    done = [
        SetDone(_amount(exercise.measure, logged), logged.load_kg)
        for logged in last_slot_sets(conn, exercise.id, training_weeks)
    ]
    return PlannedExercise(
        exercise.id,
        exercise.exercise_id,
        exercise.name,
        exercise.equipment,
        exercise.measure,
        carried_load(exercise.name, exercise.equipment, bodyweight),
        exercise.sets,
        exercise.rep_min,
        exercise.rep_max,
        exercise.notes,
        target_for(prescription, done, deload_week=deload),
        last_session(conn, exercise.exercise_id, exclude),
    )


# coverage-critical
def _amount(measure: Measure, logged: SlotSet) -> float:
    """What a set counts towards its range: seconds if timed, else reps; none counts 0."""
    amount = logged.duration_s if measure is Measure.SECONDS else logged.reps
    return amount or 0
