"""Write endpoints for logging from the app.

Workouts and sets are addressed by phone-generated UUIDs and written with
idempotent ``PUT``/``DELETE``, so an offline queue can be replayed safely.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime  # noqa: TC003  # why: FastAPI reads the annotation at runtime
from typing import Annotated, Literal, Self
from uuid import UUID  # noqa: TC003  # why: FastAPI reads the annotation at runtime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from trainer.domain.exercises import Equipment, Measure
from trainer.services.journal import (
    DuplicateExerciseError,
    InvalidWorkoutError,
    NewExercise,
    NotFoundError,
    add_exercise,
    record_set,
    record_workout,
    remove_set,
    remove_workout,
)
from trainer.storage.database import connect
from trainer.storage.history import ExerciseSummary, WorkoutDetail, current_workout
from trainer.storage.journal import JournalConflictError, SetValues

router = APIRouter(prefix="/api")

Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class WorkoutIn(BaseModel):
    """Start, update or finish a workout."""

    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    notes: Notes | None = None


class SetIn(BaseModel):
    """One set, as logged or corrected."""

    workout_client_id: UUID
    exercise_id: int
    reps: Annotated[int, Field(ge=0, le=10_000)] | None = None
    load_kg: Annotated[float, Field(ge=0, le=1_000)] | None = None
    duration_s: Annotated[float, Field(ge=0, le=86_400)] | None = None
    rpe: Annotated[int, Field(ge=1, le=10)] | None = None
    notes: Notes | None = None

    @model_validator(mode="after")
    def reps_or_duration(self) -> Self:
        """A set records reps, a duration, or both."""
        if self.reps is None and self.duration_s is None:
            message = "a set needs reps or a duration"
            raise ValueError(message)
        return self


class ExerciseIn(BaseModel):
    """A new exercise for the catalogue."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    equipment: Equipment | None = None
    muscle_groups: Annotated[str, StringConstraints(max_length=200)] | None = None
    # Distance is not creatable until sets can record a distance (cardio, later).
    measure: Literal[Measure.REPS, Measure.SECONDS] = Measure.REPS
    allow_similar: bool = False


def _database(request: Request) -> str:
    return str(request.app.state.settings.database)


@router.get("/workouts/current")
def current(request: Request) -> WorkoutDetail | None:
    """The unfinished app workout, if there is one."""
    with closing(connect(_database(request))) as conn:
        return current_workout(conn)


@router.put("/workouts/{client_id}")
def put_workout(request: Request, client_id: UUID, body: WorkoutIn) -> WorkoutDetail:
    """Create or update a workout by its client id."""
    times: tuple[datetime, datetime | None] = (body.started_at, body.ended_at)
    try:
        with closing(connect(_database(request))) as conn:
            return record_workout(conn, str(client_id), times, body.notes)
    except InvalidWorkoutError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/workouts/{client_id}", status_code=204)
def delete_workout(request: Request, client_id: UUID) -> Response:
    """Delete a workout logged in the app, with its sets."""
    with closing(connect(_database(request))) as conn:
        remove_workout(conn, str(client_id))
    return Response(status_code=204)


@router.put("/sets/{client_id}")
def put_set(request: Request, client_id: UUID, body: SetIn) -> WorkoutDetail:
    """Log or correct a set; returns the whole workout."""
    values = SetValues(body.reps, body.load_kg, body.duration_s, body.rpe, body.notes)
    placement = (str(body.workout_client_id), body.exercise_id)
    try:
        with closing(connect(_database(request))) as conn:
            return record_set(conn, str(client_id), placement, values)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except JournalConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/sets/{client_id}", status_code=204)
def delete_set(request: Request, client_id: UUID) -> Response:
    """Delete a logged set."""
    with closing(connect(_database(request))) as conn:
        remove_set(conn, str(client_id))
    return Response(status_code=204)


@router.post("/exercises", status_code=201)
def post_exercise(request: Request, body: ExerciseIn) -> ExerciseSummary:
    """Add an exercise; 409 with the matches if it exists or looks like one that does."""
    exercise = NewExercise(body.name, body.equipment, body.muscle_groups, body.measure)
    try:
        with closing(connect(_database(request))) as conn:
            return add_exercise(conn, exercise, allow_similar=body.allow_similar)
    except DuplicateExerciseError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": str(error),  # "exists" or "similar"
                "matches": [
                    {"id": match.id, "name": match.name, "equipment": match.equipment}
                    for match in error.matches
                ],
            },
        ) from error
