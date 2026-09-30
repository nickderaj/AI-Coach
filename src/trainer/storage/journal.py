"""Writes from the app: workouts and sets keyed by phone-generated client ids.

Every write is idempotent on its client id, so a phone replaying a queue of
offline changes updates what it already sent instead of duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

APP_SOURCE = "app"


class JournalConflictError(ValueError):
    """A client id is already used for a different workout or exercise."""


@dataclass(frozen=True)
class SetValues:
    """What was done in one set (the editable part of a set)."""

    reps: int | None
    load_kg: float | None
    duration_s: float | None
    rpe: int | None
    notes: str | None


def workout_id_for(conn: sqlite3.Connection, client_id: str) -> int | None:
    """The workout created under ``client_id``, if any."""
    row = conn.execute("""SELECT id FROM workouts WHERE client_id = ?""", (client_id,)).fetchone()
    return None if row is None else int(row[0])


def save_workout(
    conn: sqlite3.Connection, client_id: str, times: tuple[str, str | None], notes: str | None
) -> int:
    """Create or update the app workout ``client_id``; ``times`` is (started, ended)."""
    started_at, ended_at = times
    row = conn.execute(
        """
        INSERT INTO workouts (started_at, ended_at, notes, source, client_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (client_id) DO UPDATE SET started_at = excluded.started_at,
            ended_at = excluded.ended_at, notes = excluded.notes
        RETURNING id
        """,
        (started_at, ended_at, notes, APP_SOURCE, client_id),
    ).fetchone()
    workout_id: int = row[0]
    return workout_id


def delete_workout(conn: sqlite3.Connection, client_id: str) -> bool:
    """Delete an app workout and its sets; ``False`` if there was none."""
    cursor = conn.execute("""DELETE FROM workouts WHERE client_id = ?""", (client_id,))
    return cursor.rowcount > 0


def _next_slot(conn: sqlite3.Connection, workout_id: int, exercise_id: int) -> tuple[int, int]:
    """(position, set number) for a new set.

    Continues the last block if it is the same exercise, otherwise starts a new
    block after it.
    """
    last = conn.execute(
        """
        SELECT exercise_position, exercise_id, max(set_number) FROM workout_sets
        WHERE workout_id = ? GROUP BY exercise_position
        ORDER BY exercise_position DESC LIMIT 1
        """,
        (workout_id,),
    ).fetchone()
    if last is None:
        return 1, 1
    position, last_exercise, last_set = last
    if last_exercise == exercise_id:
        return position, last_set + 1
    return position + 1, 1


def save_set(
    conn: sqlite3.Connection, client_id: str, placement: tuple[int, int], values: SetValues
) -> int:
    """Create set ``client_id`` in (workout, exercise) ``placement``, or update its values.

    Raises:
        JournalConflictError: if ``client_id`` already names a set in another
            workout or of another exercise.
    """
    workout_id, exercise_id = placement
    existing = conn.execute(
        """SELECT id, workout_id, exercise_id FROM workout_sets WHERE client_id = ?""",
        (client_id,),
    ).fetchone()
    fields = (values.reps, values.load_kg, values.duration_s, values.rpe, values.notes)
    if existing is not None:
        set_id, workout, exercise = existing
        if (workout, exercise) != placement:
            message = f"set {client_id} belongs to another workout or exercise"
            raise JournalConflictError(message)
        conn.execute(
            """
            UPDATE workout_sets SET reps = ?, load_kg = ?, duration_s = ?, rpe = ?, notes = ?
            WHERE id = ?
            """,
            (*fields, set_id),
        )
        return int(set_id)
    position, set_number = _next_slot(conn, workout_id, exercise_id)
    row = conn.execute(
        """
        INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number,
            reps, load_kg, duration_s, rpe, notes, client_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (workout_id, exercise_id, position, set_number, *fields, client_id),
    ).fetchone()
    return int(row[0])


def delete_set(conn: sqlite3.Connection, client_id: str) -> bool:
    """Delete set ``client_id``; ``False`` if there was none."""
    cursor = conn.execute("""DELETE FROM workout_sets WHERE client_id = ?""", (client_id,))
    return cursor.rowcount > 0
