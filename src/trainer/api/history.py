"""Read-only history endpoints."""

from __future__ import annotations

from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from trainer.storage.database import connect
from trainer.storage.history import (
    ExerciseHistory,
    ExerciseSummary,
    WorkoutDetail,
    WorkoutSummary,
    exercise_history,
    get_workout,
    list_exercises,
    list_workouts,
)

router = APIRouter(prefix="/api")


def _database(request: Request) -> str:
    return str(request.app.state.settings.database)


@router.get("/workouts")
def workouts(
    request: Request, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[WorkoutSummary]:
    """Recent workouts, newest first."""
    with closing(connect(_database(request))) as conn:
        return list_workouts(conn, limit)


@router.get("/workouts/{workout_id}")
def workout(request: Request, workout_id: int) -> WorkoutDetail:
    """One workout with all its sets."""
    with closing(connect(_database(request))) as conn:
        found = get_workout(conn, workout_id)
    if found is None:
        raise HTTPException(status_code=404, detail="workout not found")
    return found


@router.get("/exercises")
def exercises(request: Request) -> list[ExerciseSummary]:
    """The exercise catalogue, most recently trained first."""
    with closing(connect(_database(request))) as conn:
        return list_exercises(conn)


@router.get("/exercises/{exercise_id}/history")
def history(request: Request, exercise_id: int) -> ExerciseHistory:
    """Every session of one exercise, newest first."""
    with closing(connect(_database(request))) as conn:
        found = exercise_history(conn, exercise_id)
    if found is None:
        raise HTTPException(status_code=404, detail="exercise not found")
    return found
