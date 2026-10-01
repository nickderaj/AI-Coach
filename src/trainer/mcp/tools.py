"""The coach's tools: reading the training log (D10), and proposing a program (D12)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trainer.mcp.protocol import Json, Tool, ToolError
from trainer.services.programs import ProgramIn, programs
from trainer.storage.database import connect_readonly
from trainer.storage.history import (
    WorkoutNotFoundError,
    exercise_history,
    get_workout,
    list_exercises,
    list_workouts,
)
from trainer.storage.profile import read_profile

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from trainer.mcp.proposals import ProgramsApi


# SQLite's INTEGER is signed 64-bit, and row ids start at 1. A larger Python int
# would raise OverflowError in the query instead of finding nothing.
MAX_ROW_ID = 2**63 - 1
# A plain alias, not a `type` statement, so the schema shows the bounds inline.
RowId = Annotated[int, Field(ge=1, le=MAX_ROW_ID)]


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecentWorkouts(_Arguments):
    """Arguments of ``recent_workouts``."""

    limit: Annotated[int, Field(ge=1, le=50, description="How many workouts, newest first.")] = 10


class Workout(_Arguments):
    """Arguments of ``get_workout``."""

    workout_id: Annotated[RowId, Field(description="A workout id from recent_workouts.")]


class Catalogue(_Arguments):
    """Arguments of ``list_exercises``: none."""


class History(_Arguments):
    """Arguments of ``exercise_history``."""

    exercise_id: Annotated[RowId, Field(description="An exercise id from list_exercises.")]
    sessions: Annotated[
        int, Field(ge=1, le=100, description="How many sessions, newest first.")
    ] = 20


class BodyWeight(_Arguments):
    """Arguments of ``body_weight``: none."""


class CurrentProgram(_Arguments):
    """Arguments of ``current_program``: none."""


def _recent_workouts(conn: sqlite3.Connection, arguments: RecentWorkouts) -> object:
    return [asdict(summary) for summary in list_workouts(conn, arguments.limit)]


def _get_workout(conn: sqlite3.Connection, arguments: Workout) -> object:
    try:
        return asdict(get_workout(conn, arguments.workout_id))
    except WorkoutNotFoundError as error:
        message = f"there is no workout {arguments.workout_id}"
        raise ToolError(message) from error


def _list_exercises(conn: sqlite3.Connection, _arguments: Catalogue) -> object:
    return [asdict(summary) for summary in list_exercises(conn)]


def _exercise_history(conn: sqlite3.Connection, arguments: History) -> object:
    found = exercise_history(conn, arguments.exercise_id)
    if found is None:
        message = f"there is no exercise {arguments.exercise_id}"
        raise ToolError(message)
    return asdict(replace(found, sessions=found.sessions[: arguments.sessions]))


def _body_weight(conn: sqlite3.Connection, _arguments: BodyWeight) -> object:
    return asdict(read_profile(conn))


def _current_program(conn: sqlite3.Connection, _arguments: CurrentProgram) -> object:
    return asdict(programs(conn))


# Each tool's description, argument model and answer, by name.
_TOOLS: dict[str, tuple[str, type[_Arguments], Callable[[sqlite3.Connection, Any], object]]] = {
    "recent_workouts": (
        (
            "The most recent workouts, newest first: when, each exercise with its set "
            "count and best set, the total set count and volume in kg."
        ),
        RecentWorkouts,
        _recent_workouts,
    ),
    "get_workout": (
        (
            "One workout with every set: reps, load_kg, duration_s, rpe and notes per set, "
            "grouped by exercise in the order done. carried_kg is the body weight each rep "
            "of a bodyweight exercise moves on top of load_kg."
        ),
        Workout,
        _get_workout,
    ),
    "list_exercises": (
        (
            "The exercise catalogue: id, name, equipment, muscle groups, measure (reps or "
            "seconds), how many workouts included it, when it was last done, best load."
        ),
        Catalogue,
        _list_exercises,
    ),
    "exercise_history": (
        (
            "Every set of one exercise, by session, newest first, with carried_kg for "
            "bodyweight exercises. Use it for progress, records and what was done last time."
        ),
        History,
        _exercise_history,
    ),
    "body_weight": (
        "The owner's body weight in kg, or null if not set.",
        BodyWeight,
        _body_weight,
    ),
    "current_program": (
        (
            "The program being trained (active), with every day, block and exercise: "
            "exercise_id, sets, rep_min-rep_max (seconds if timed), start_load_kg; a block "
            "of more than one exercise is a superset. Also the next week and day to train "
            "(next; week 7 is the deload week), and any proposal still waiting for the owner "
            "(proposed). Read it before proposing a change to a program."
        ),
        CurrentProgram,
        _current_program,
    ),
}


PROPOSE_DESCRIPTION = (
    "Propose a training program for the owner to accept in the app's Program screen. It "
    "replaces any earlier proposal and never changes the program being trained. A program "
    "is six training weeks then a deload week; its days repeat every week in order. A day "
    "is blocks in order: one exercise, or two or three done as a superset. Use exercise ids "
    "from list_exercises. Give each exercise its sets and a rep range (seconds for a timed "
    "exercise). The app sets every load after the first session from the log, by double "
    "progression, so give start_load_kg only for the first session, from exercise_history. "
    "To refine a proposal, propose it again in full."
)


def tools(database: Path, programs_api: ProgramsApi | None = None) -> dict[str, Tool]:
    """The tool set over the database at ``database``, opened read-only per call.

    ``propose_program`` is offered only with ``programs_api``, the way to save one.
    """
    found = {
        name: Tool(name, description, model.model_json_schema(), _caller(database, model, answer))
        for name, (description, model, answer) in _TOOLS.items()
    }
    if programs_api is not None:
        schema = inline_refs(ProgramIn.model_json_schema())
        found["propose_program"] = Tool(
            "propose_program", PROPOSE_DESCRIPTION, schema, _proposer(programs_api)
        )
    return found


def inline_refs(schema: Json) -> Json:
    """``schema``, which has ``$defs``, with each ``$ref`` replaced by its definition.

    Model providers differ in how much JSON Schema they take; a plain nested
    schema is the most widely understood.
    """
    definitions: Json = schema["$defs"]
    return {key: _resolve(value, definitions) for key, value in schema.items() if key != "$defs"}


def _resolve(node: object, definitions: Json) -> object:
    if isinstance(node, list):
        return [_resolve(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    reference = node.get("$ref")
    if isinstance(reference, str):
        return _resolve(definitions[reference.removeprefix("#/$defs/")], definitions)
    return {key: _resolve(value, definitions) for key, value in node.items()}


def _proposer(programs_api: ProgramsApi) -> Callable[[Json], object]:
    def call(arguments: Json) -> object:
        try:
            program = ProgramIn.model_validate(arguments)
        except ValidationError as error:
            raise ToolError(_describe(error)) from error
        saved = programs_api.propose(program)
        return {
            "proposed": saved,
            "next": "The owner reviews it in the app's Program screen and accepts it there.",
        }

    return call


def _caller(
    database: Path,
    model: type[_Arguments],
    answer: Callable[[sqlite3.Connection, Any], object],
) -> Callable[[Json], object]:
    def call(arguments: Json) -> object:
        try:
            parsed = model.model_validate(arguments)
        except ValidationError as error:
            raise ToolError(_describe(error)) from error
        try:
            with closing(connect_readonly(database)) as conn:
                return answer(conn, parsed)
        except sqlite3.OperationalError as error:
            message = f"the training log cannot be read right now ({error})"
            raise ToolError(message) from error

    return call


def _describe(error: ValidationError) -> str:
    problems = "; ".join(
        # Each problem names where it is: "days.0.blocks.1.exercises.0.rep_max".
        f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}"
        for problem in error.errors()
    )
    return f"invalid arguments: {problems}"
