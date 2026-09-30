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


def create_exercise(conn: sqlite3.Connection, spec: ExerciseSpec) -> int:
    """Create a new exercise and return its id.

    Raises:
        sqlite3.IntegrityError: if the name is already taken.
    """
    row = conn.execute(
        """
        INSERT INTO exercises (name, display_name, equipment, muscle_groups, measure)
        VALUES (?, ?, ?, ?, ?)
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
    return int(row[0])


def catalogue_entries(conn: sqlite3.Connection) -> list[tuple[str, str | None]]:
    """Every (name, equipment) in the catalogue.

    Display names, and aliases with the equipment of the exercise they point at.
    """
    return [
        (str(row[0]), row[1])
        for row in conn.execute(
            """
            SELECT display_name, equipment FROM exercises
            UNION ALL SELECT a.alias, e.equipment
            FROM exercise_aliases a JOIN exercises e ON e.id = a.exercise_id
            ORDER BY 1
            """
        )
    ]


def known_names(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Every (exercise id, name) a new exercise could collide with.

    Display names and aliases, ordered by exercise id.
    """
    return [
        (int(row[0]), str(row[1]))
        for row in conn.execute(
            """
            SELECT id, display_name FROM exercises
            UNION ALL SELECT exercise_id, alias FROM exercise_aliases
            ORDER BY 1, 2
            """
        )
    ]
