"""Seeding the catalogue with common exercises, so they need not be added by hand."""

from __future__ import annotations

import csv
import io
from importlib.resources import files
from typing import TYPE_CHECKING

from trainer.domain.exercises import Equipment, Measure, is_catalogued
from trainer.services.journal import NewExercise, spec_for
from trainer.storage.catalogue import catalogue_entries, create_exercise
from trainer.storage.database import write_transaction

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

COMMON_EXERCISES = "data/common_exercises.csv"


def common_exercises() -> list[NewExercise]:
    """The shipped list of common exercises, in file order."""
    return parse_exercises(files("trainer").joinpath(COMMON_EXERCISES).read_bytes().decode())


def parse_exercises(text: str) -> list[NewExercise]:
    """Exercises from CSV with a header: name, equipment, measure, muscle_groups."""
    return [
        NewExercise(
            name=row["name"],
            equipment=Equipment(row["equipment"]),
            muscle_groups=row["muscle_groups"] or None,
            measure=Measure(row["measure"]),
        )
        for row in csv.DictReader(io.StringIO(text))
    ]


def describe(exercise: NewExercise) -> str:
    """One line for a listing: "Goblet Squat (dumbbell)"."""
    return f"{exercise.name} ({exercise.equipment.value})"


def missing_exercises(
    conn: sqlite3.Connection, exercises: Iterable[NewExercise]
) -> list[NewExercise]:
    """Those of ``exercises`` the catalogue does not have yet, in order.

    An exercise is there already when ``is_catalogued`` says so, which lets a
    variant ("Incline Bench Press") in but keeps a restatement ("Dip" beside
    "Dips", "Bodyweight Squat" beside a bodyweight "Squat") out.
    """
    entries = catalogue_entries(conn)
    missing: list[NewExercise] = []
    for exercise in exercises:
        equipment = exercise.equipment.value
        if not is_catalogued(exercise.name, equipment, entries):
            missing.append(exercise)
            entries.append((exercise.name, equipment))
    return missing


def seed_exercises(conn: sqlite3.Connection, exercises: Iterable[NewExercise]) -> list[NewExercise]:
    """Add the exercises the catalogue is missing; returns those added. Re-runnable."""
    with write_transaction(conn):
        added = missing_exercises(conn, exercises)
        for exercise in added:
            create_exercise(conn, spec_for(exercise))
    return added
