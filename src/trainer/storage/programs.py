"""Programs: their days, blocks and exercises, and where training has got to."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import groupby
from typing import TYPE_CHECKING

from trainer.domain.exercises import Measure
from trainer.domain.programs import Position, load_increment

if TYPE_CHECKING:
    import sqlite3


class ProgramStatus(StrEnum):
    """Where a program is in its life."""

    PROPOSED = "proposed"  # by the coach, awaiting the owner
    ACTIVE = "active"  # the one being trained
    ARCHIVED = "archived"  # replaced by another


@dataclass(frozen=True)
class SlotSpec:
    """An exercise to put in a block: sets of a range of reps (or seconds)."""

    exercise_id: int
    sets: int
    rep_min: int
    rep_max: int
    start_load_kg: float | None
    notes: str | None


@dataclass(frozen=True)
class BlockSpec:
    """A block to put in a day: more than one exercise makes a superset."""

    rest_s: int
    exercises: tuple[SlotSpec, ...]


@dataclass(frozen=True)
class DaySpec:
    """A day to put in a program."""

    name: str
    blocks: tuple[BlockSpec, ...]


@dataclass(frozen=True)
class ProgramSpec:
    """A program to save."""

    name: str
    notes: str | None
    training_weeks: int
    days: tuple[DaySpec, ...]


@dataclass(frozen=True)
class ProgramExercise:
    """An exercise in a block, with its catalogue details and load step."""

    id: int
    exercise_id: int
    name: str
    equipment: str | None
    measure: Measure
    sets: int
    rep_min: int
    rep_max: int
    start_load_kg: float | None
    notes: str | None
    increment_kg: float | None


@dataclass(frozen=True)
class ProgramBlock:
    """A block of a day: one exercise, or a superset of several, in order."""

    rest_s: int
    exercises: list[ProgramExercise]


@dataclass(frozen=True)
class ProgramDay:
    """A day of the program, repeated every week; its blocks in order."""

    id: int
    name: str
    blocks: list[ProgramBlock]


@dataclass(frozen=True)
class Program:
    """A whole program; its days in order (day 1 first)."""

    id: int
    name: str
    notes: str | None
    training_weeks: int
    status: ProgramStatus
    created_at: str
    started_at: str | None
    days: list[ProgramDay]


def insert_program(
    conn: sqlite3.Connection, spec: ProgramSpec, status: ProgramStatus, created_at: str
) -> int:
    """Save a program with every day, block and exercise; return its id."""
    program_id = _insert(
        conn,
        """
        INSERT INTO programs (name, notes, training_weeks, status, created_at)
        VALUES (?, ?, ?, ?, ?) RETURNING id
        """,
        (spec.name, spec.notes, spec.training_weeks, status.value, created_at),
    )
    for day_position, day in enumerate(spec.days, start=1):
        day_id = _insert(
            conn,
            """
            INSERT INTO program_days (program_id, position, name) VALUES (?, ?, ?) RETURNING id
            """,
            (program_id, day_position, day.name),
        )
        for block_position, block in enumerate(day.blocks, start=1):
            block_id = _insert(
                conn,
                """
                INSERT INTO program_blocks (day_id, position, rest_s) VALUES (?, ?, ?)
                RETURNING id
                """,
                (day_id, block_position, block.rest_s),
            )
            conn.executemany(
                """
                INSERT INTO block_exercises (block_id, position, exercise_id, sets, rep_min,
                    rep_max, start_load_kg, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (block_id, position, *_slot_values(slot))
                    for position, slot in enumerate(block.exercises, start=1)
                ],
            )
    return program_id


def _slot_values(slot: SlotSpec) -> tuple[object, ...]:
    return (slot.exercise_id, slot.sets, slot.rep_min, slot.rep_max, slot.start_load_kg, slot.notes)


def _insert(conn: sqlite3.Connection, sql: str, parameters: tuple[object, ...]) -> int:
    return int(conn.execute(sql, parameters).fetchone()[0])


def program_with_status(conn: sqlite3.Connection, status: ProgramStatus) -> int | None:
    """The id of the proposed or the active program, if there is one."""
    row = conn.execute("""SELECT id FROM programs WHERE status = ?""", (status.value,)).fetchone()
    return None if row is None else int(row[0])


def delete_program(conn: sqlite3.Connection, program_id: int) -> None:
    """Delete a program that was never trained from, with its days."""
    conn.execute("""DELETE FROM programs WHERE id = ?""", (program_id,))


def activate_program(conn: sqlite3.Connection, program_id: int, started_at: str) -> None:
    """Make a program the active one; the one it replaces is archived."""
    conn.execute("""UPDATE programs SET status = 'archived' WHERE status = 'active'""")
    conn.execute(
        """UPDATE programs SET status = 'active', started_at = ? WHERE id = ?""",
        (started_at, program_id),
    )


class ProgramNotFoundError(LookupError):
    """No program has the requested id."""


def get_program(conn: sqlite3.Connection, program_id: int) -> Program:
    """A program with all its days, blocks and exercises.

    Raises:
        ProgramNotFoundError: if there is no such program.
    """
    row = conn.execute(
        """
        SELECT id, name, notes, training_weeks, status, created_at, started_at
        FROM programs WHERE id = ?
        """,
        (program_id,),
    ).fetchone()
    if row is None:
        message = f"no program {program_id}"
        raise ProgramNotFoundError(message)
    found_id, name, notes, training_weeks, status, created_at, started_at = row
    return Program(
        found_id,
        name,
        notes,
        training_weeks,
        ProgramStatus(status),
        created_at,
        started_at,
        _days(conn, program_id),
    )


def _days(conn: sqlite3.Connection, program_id: int) -> list[ProgramDay]:
    rows = conn.execute(
        """
        SELECT d.id, d.name, b.id, b.rest_s, x.id, x.exercise_id, e.display_name, e.equipment,
            e.measure, x.sets, x.rep_min, x.rep_max, x.start_load_kg, x.notes,
            e.load_increment_kg
        FROM program_days d
        JOIN program_blocks b ON b.day_id = d.id
        JOIN block_exercises x ON x.block_id = b.id
        JOIN exercises e ON e.id = x.exercise_id
        WHERE d.program_id = ?
        ORDER BY d.position, b.position, x.position
        """,
        (program_id,),
    ).fetchall()
    return [_day(list(group)) for _, group in groupby(rows, key=_day_id)]


def _day_id(row: sqlite3.Row) -> int:
    return int(row[0])


def _block_id(row: sqlite3.Row) -> int:
    return int(row[2])


def _day(rows: list[sqlite3.Row]) -> ProgramDay:
    """``rows`` are one day's, in order; columns 0-1 are the day's."""
    day_id, name = rows[0][:2]
    return ProgramDay(day_id, name, [_block(list(group)) for _, group in groupby(rows, _block_id)])


def _block(rows: list[sqlite3.Row]) -> ProgramBlock:
    """``rows`` are one block's, in order; column 3 is its rest."""
    return ProgramBlock(rows[0][3], [_exercise(row) for row in rows])


def _exercise(row: sqlite3.Row) -> ProgramExercise:
    """Columns 4 on are the block exercise's, its catalogue entry's and its own load step."""
    block_exercise_id, exercise_id, name, equipment, measure = row[4:9]
    sets, rep_min, rep_max, start_load_kg, notes, increment = row[9:]
    return ProgramExercise(
        block_exercise_id,
        exercise_id,
        name,
        equipment,
        Measure(measure),
        sets,
        rep_min,
        rep_max,
        start_load_kg,
        notes,
        load_increment(equipment, increment),
    )


def last_position(conn: sqlite3.Connection, program_id: int) -> Position | None:
    """Week and day of the program's most recently started finished workout, if any."""
    row = conn.execute(
        """
        SELECT w.program_week, d.position FROM workouts w
        JOIN program_days d ON d.id = w.program_day_id
        WHERE d.program_id = ? AND w.ended_at IS NOT NULL
        ORDER BY w.started_at DESC, w.id DESC LIMIT 1
        """,
        (program_id,),
    ).fetchone()
    return None if row is None else Position(row[0], row[1])


@dataclass(frozen=True)
class SlotSet:
    """A set logged for a program exercise."""

    reps: int | None
    load_kg: float | None
    duration_s: float | None


def last_slot_sets(
    conn: sqlite3.Connection, block_exercise_id: int, up_to_week: int
) -> list[SlotSet]:
    """The sets of the last finished session of a program exercise, in order.

    Only sessions from weeks up to ``up_to_week`` count, so the deload week
    never feeds progression.
    """
    rows = conn.execute(
        """
        SELECT reps, load_kg, duration_s FROM workout_sets
        WHERE block_exercise_id = ?1 AND workout_id = (
            SELECT w.id FROM workouts w JOIN workout_sets s ON s.workout_id = w.id
            WHERE s.block_exercise_id = ?1 AND w.ended_at IS NOT NULL
                AND w.program_week <= ?2
            ORDER BY w.started_at DESC, w.id DESC LIMIT 1
        )
        ORDER BY set_number
        """,
        (block_exercise_id, up_to_week),
    ).fetchall()
    return [SlotSet(*row) for row in rows]


@dataclass(frozen=True)
class SlotPlace:
    """Which program day and exercise a block exercise belongs to."""

    day_id: int
    exercise_id: int


def slot_place(conn: sqlite3.Connection, block_exercise_id: int) -> SlotPlace | None:
    """The day and exercise of a block exercise, or ``None`` if there is none."""
    row = conn.execute(
        """
        SELECT b.day_id, x.exercise_id FROM block_exercises x
        JOIN program_blocks b ON b.id = x.block_id WHERE x.id = ?
        """,
        (block_exercise_id,),
    ).fetchone()
    return None if row is None else SlotPlace(row[0], row[1])


def set_days(conn: sqlite3.Connection, workout_client_id: str) -> set[int]:
    """The program days that the program sets of a workout belong to."""
    return {
        int(row[0])
        for row in conn.execute(
            """
            SELECT b.day_id FROM workout_sets s
            JOIN workouts w ON w.id = s.workout_id
            JOIN block_exercises x ON x.id = s.block_exercise_id
            JOIN program_blocks b ON b.id = x.block_id
            WHERE w.client_id = ?
            """,
            (workout_client_id,),
        )
    }


def day_weeks(conn: sqlite3.Connection, day_id: int) -> int | None:
    """How many weeks, deload included, the program of a day has; ``None`` if no such day."""
    row = conn.execute(
        """
        SELECT p.training_weeks + 1 FROM program_days d
        JOIN programs p ON p.id = d.program_id WHERE d.id = ?
        """,
        (day_id,),
    ).fetchone()
    return None if row is None else int(row[0])
