"""Seeding the catalogue with common exercises."""

import sqlite3

import pytest

from trainer.domain.exercises import Equipment, Measure, is_catalogued
from trainer.services.journal import NewExercise
from trainer.services.seed import (
    common_exercises,
    describe,
    missing_exercises,
    parse_exercises,
    seed_exercises,
)
from trainer.storage.catalogue import add_alias, catalogue_entries, resolve


def names(exercises: list[NewExercise]) -> list[str]:
    return [exercise.name for exercise in exercises]


def test_parse_exercises() -> None:
    text = (
        "name,equipment,measure,muscle_groups\n"
        'Goblet Squat,dumbbell,reps,"quads,glutes"\n'
        "Plank,bodyweight,seconds,\n"
    )

    assert parse_exercises(text) == [
        NewExercise("Goblet Squat", Equipment.DUMBBELL, "quads,glutes", Measure.REPS),
        NewExercise("Plank", Equipment.BODYWEIGHT, None, Measure.SECONDS),
    ]


def test_every_exercise_needs_equipment() -> None:
    with pytest.raises(ValueError, match="''"):
        parse_exercises("name,equipment,measure,muscle_groups\nPlank,,seconds,\n")


def test_describe() -> None:
    goblet, plank = parse_exercises(
        "name,equipment,measure,muscle_groups\n"
        "Goblet Squat,dumbbell,reps,quads\n"
        "Plank,bodyweight,seconds,core\n"
    )

    assert describe(goblet) == "Goblet Squat (dumbbell)"
    assert describe(plank) == "Plank (bodyweight)"


def test_the_shipped_list_goes_into_an_empty_catalogue_whole() -> None:
    exercises = common_exercises()
    entries: list[tuple[str, str | None]] = []
    for exercise in exercises:
        equipment = exercise.equipment.value
        assert not is_catalogued(exercise.name, equipment, entries), exercise.name
        entries.append((exercise.name, equipment))

    assert len(exercises) >= 80
    assert NewExercise("Plank", Equipment.BODYWEIGHT, "core", Measure.SECONDS) in exercises


def test_seeding_adds_only_what_is_missing(imported: sqlite3.Connection) -> None:
    exercises = parse_exercises(
        "name,equipment,measure,muscle_groups\n"
        "Pull-ups,bodyweight,reps,back\n"  # the fixture's Pull-up
        "Incline Bench Press,barbell,reps,chest\n"  # a variant of its bench press
        "Dumbbell Bench Press,dumbbell,reps,chest\n"  # its bench press, other equipment
        "Chin-up,bodyweight,reps,back\n"
        "Chin-ups,bodyweight,reps,back\n"  # a repeat within the list
        "Dumbbell Fly,dumbbell,reps,chest\n"
        "Cable Fly,cable,reps,chest\n"  # the same words as the last, other equipment
        "Plank,bodyweight,seconds,core\n"
    )
    expected = [
        "Incline Bench Press",
        "Dumbbell Bench Press",
        "Chin-up",
        "Dumbbell Fly",
        "Cable Fly",
        "Plank",
    ]

    assert names(missing_exercises(imported, exercises)) == expected
    assert resolve(imported, "incline bench press") is None  # a dry run writes nothing

    added = seed_exercises(imported, exercises)

    assert names(added) == expected
    chin_up = imported.execute(
        "SELECT display_name, equipment, muscle_groups, measure FROM exercises WHERE name = ?",
        ("chin-up",),
    ).fetchone()
    assert tuple(chin_up) == ("Chin-up", "bodyweight", "back", "reps")
    assert seed_exercises(imported, exercises) == []  # re-runnable


def test_aliases_count_as_catalogued(db: sqlite3.Connection) -> None:
    seed_exercises(db, parse_exercises("name,equipment,measure,muscle_groups\nRow,cable,reps,\n"))
    row = resolve(db, "row")
    assert row is not None
    add_alias(db, "seated cable row", row)

    assert catalogue_entries(db) == [("Row", "cable"), ("seated cable row", "cable")]
    assert (
        missing_exercises(
            db,
            parse_exercises("name,equipment,measure,muscle_groups\nSeated Row,cable,reps,\n"),
        )
        == []
    )
