"""Exercise catalogue repository."""

import sqlite3

from trainer.domain.exercises import Measure
from trainer.storage.catalogue import ExerciseSpec, add_alias, resolve, upsert_exercise

BENCH = ExerciseSpec(
    name="Barbell  Bench Press",
    display_name="Barbell Bench Press",
    equipment="barbell",
    muscle_groups="chest,triceps",
    measure=Measure.REPS,
)


def rows(db: sqlite3.Connection) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in db.execute(
            "SELECT id, name, display_name, equipment, muscle_groups, measure FROM exercises"
        )
    ]


def test_upsert_creates_with_a_normalised_name(db: sqlite3.Connection) -> None:
    exercise_id = upsert_exercise(db, BENCH)

    assert rows(db) == [
        (
            exercise_id,
            "barbell bench press",
            "Barbell Bench Press",
            "barbell",
            "chest,triceps",
            "reps",
        )
    ]


def test_upsert_updates_in_place_and_keeps_the_id(db: sqlite3.Connection) -> None:
    first = upsert_exercise(db, BENCH)
    changed = ExerciseSpec("barbell bench press", "Bench", None, None, Measure.SECONDS)

    assert upsert_exercise(db, changed) == first
    assert rows(db) == [(first, "barbell bench press", "Bench", None, None, "seconds")]


def test_resolve_by_name_or_alias(db: sqlite3.Connection) -> None:
    exercise_id = upsert_exercise(db, BENCH)
    add_alias(db, "  Bench ", exercise_id)

    assert resolve(db, "BARBELL bench   press") == exercise_id
    assert resolve(db, "bench") == exercise_id
    assert resolve(db, "squat") is None


def test_alias_can_be_repointed(db: sqlite3.Connection) -> None:
    bench = upsert_exercise(db, BENCH)
    decline = upsert_exercise(
        db, ExerciseSpec("decline barbell bench press", "Decline", "barbell", None, Measure.REPS)
    )
    add_alias(db, "bench", bench)

    add_alias(db, "bench", decline)

    assert [
        tuple(row) for row in db.execute("SELECT alias, exercise_id FROM exercise_aliases")
    ] == [("bench", decline)]
