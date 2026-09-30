"""Training log repository."""

import sqlite3

from trainer.domain.exercises import Measure
from trainer.storage.catalogue import ExerciseSpec, upsert_exercise
from trainer.storage.log import (
    BodyMetricRecord,
    CardioRecord,
    SetRecord,
    WorkoutRecord,
    delete_source,
    insert_body_metric,
    insert_cardio,
    insert_set,
    insert_workout,
)


def seed(db: sqlite3.Connection, source: str) -> int:
    exercise_id = upsert_exercise(db, ExerciseSpec("x", "X", None, None, Measure.REPS))
    workout_id = insert_workout(db, WorkoutRecord("2026-01-01T10:00:00+00:00", None, None, source))
    insert_set(db, SetRecord(workout_id, exercise_id, 1, 1, reps=5))
    insert_body_metric(
        db, BodyMetricRecord("2026-01-01T09:00:00+00:00", "weight_kg", 70, "kg", source)
    )
    insert_cardio(db, CardioRecord("2026-01-02T09:00:00+00:00", "Run", 1800, 5000, None, source))
    return workout_id


def counts(db: sqlite3.Connection) -> tuple[int, ...]:
    return tuple(
        db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608  # why: fixed table names
        for table in ("workouts", "workout_sets", "body_metrics", "cardio_sessions", "exercises")
    )


def test_inserts_round_trip(db: sqlite3.Connection) -> None:
    exercise_id = upsert_exercise(db, ExerciseSpec("x", "X", None, None, Measure.REPS))
    record = WorkoutRecord("2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00+00:00", "n", "test")
    workout_id = insert_workout(db, record)
    insert_set(db, SetRecord(workout_id, exercise_id, 2, 3, 8, 60.5, 30.0, 9, "note"))
    insert_body_metric(
        db, BodyMetricRecord("2026-01-01T09:00:00+00:00", "weight_kg", 70.5, "kg", "test")
    )
    insert_cardio(
        db, CardioRecord("2026-01-02T09:00:00+00:00", "Run", 1800.0, 5000.0, "easy", "test")
    )

    assert tuple(db.execute("SELECT * FROM workouts").fetchone()) == (
        workout_id,
        "2026-01-01T10:00:00+00:00",
        "2026-01-01T11:00:00+00:00",
        "n",
        "test",
        None,
    )
    assert tuple(
        db.execute(
            "SELECT workout_id, exercise_id, exercise_position, set_number, reps, load_kg, "
            "duration_s, rpe, notes, client_id FROM workout_sets"
        ).fetchone()
    ) == (workout_id, exercise_id, 2, 3, 8, 60.5, 30.0, 9, "note", None)
    assert tuple(
        db.execute("SELECT measured_at, metric, value, unit, source FROM body_metrics").fetchone()
    ) == ("2026-01-01T09:00:00+00:00", "weight_kg", 70.5, "kg", "test")
    assert tuple(
        db.execute(
            "SELECT started_at, activity, duration_s, distance_m, notes, source "
            "FROM cardio_sessions"
        ).fetchone()
    ) == ("2026-01-02T09:00:00+00:00", "Run", 1800.0, 5000.0, "easy", "test")


def test_set_defaults_are_empty(db: sqlite3.Connection) -> None:
    exercise_id = upsert_exercise(db, ExerciseSpec("x", "X", None, None, Measure.REPS))
    workout_id = insert_workout(db, WorkoutRecord("t", None, None, "test"))

    insert_set(db, SetRecord(workout_id, exercise_id, 1, 1))

    assert tuple(
        db.execute("SELECT reps, load_kg, duration_s, rpe, notes FROM workout_sets").fetchone()
    ) == (None, None, None, None, None)


def test_delete_source_removes_only_that_source_and_cascades(db: sqlite3.Connection) -> None:
    seed(db, "v1")
    kept = seed(db, "app")

    delete_source(db, "v1")

    assert counts(db) == (1, 1, 1, 1, 1)
    assert db.execute("SELECT workout_id FROM workout_sets").fetchone()[0] == kept
