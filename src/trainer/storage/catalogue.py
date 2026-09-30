"""The exercise catalogue: exercises and the aliases that resolve to them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trainer.domain.exercises import Measure, normalise_name

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True)
class ExerciseSpec:
    """An exercise to create or update, keyed by its normalised name."""

    name: str
    display_name: str
    equipment: str | None
    muscle_groups: str | None
    measure: Measure


def upsert_exercise(conn: sqlite3.Connection, spec: ExerciseSpec) -> int:
    """Create the exercise, or update the one with the same name; return its id."""
    row = conn.execute(
        """
        INSERT INTO exercises (name, display_name, equipment, muscle_groups, measure)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (name) DO UPDATE SET display_name = excluded.display_name,
            equipment = excluded.equipment, muscle_groups = excluded.muscle_groups,
            measure = excluded.measure
        RETURNING id
        """,
        (
            normalise_name(spec.name),
            spec.display_name,
            spec.equipment,
            spec.muscle_groups,
            spec.measure.value,
        ),
    ).fetchone()
    exercise_id: int = row[0]
    return exercise_id


def add_alias(conn: sqlite3.Connection, alias: str, exercise_id: int) -> None:
    """Point ``alias`` (normalised) at an exercise, replacing any previous target."""
    conn.execute(
        """
        INSERT INTO exercise_aliases (alias, exercise_id) VALUES (?, ?)
        ON CONFLICT (alias) DO UPDATE SET exercise_id = excluded.exercise_id
        """,
        (normalise_name(alias), exercise_id),
    )


def resolve(conn: sqlite3.Connection, text: str) -> int | None:
    """The id of the exercise named, or aliased, by ``text``."""
    key = normalise_name(text)
    row = conn.execute(
        """
        SELECT id FROM exercises WHERE name = ?
        UNION ALL SELECT exercise_id FROM exercise_aliases WHERE alias = ?
        LIMIT 1
        """,
        (key, key),
    ).fetchone()
    return None if row is None else int(row[0])
