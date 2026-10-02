"""One-off, re-runnable import from the v1 gym bot's SQLite database.

The v1 database is only read. Everything written here is tagged
``source = 'v1'`` and replaced on every run inside one transaction, so the
import can be repeated safely; exercises are upserted by name, so their ids
stay stable across runs.

v1 timestamps are ISO-8601, with an offset or (for rows migrated from the
older ultron bot) without one; values without an offset are UTC.
"""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from trainer.domain.exercises import Equipment, Measure
from trainer.storage.catalogue import ExerciseSpec, add_alias, resolve, upsert_exercise
from trainer.storage.database import connect, migrate
from trainer.storage.log import (
    BodyMetricRecord,
    CardioRecord,
    SetRecord,
    WorkoutRecord,
    delete_source,
    exercise_names,
    insert_body_metric,
    insert_cardio,
    insert_set,
    insert_workout,
    source_rows,
)

if TYPE_CHECKING:
    import sqlite3

    from trainer.storage.log import Row

SOURCE = "v1"

# Names the owner used in v1 before its catalogue was cleaned up, mapped to the
# exercise they now resolve to. Weight-suffixed junk names are not carried over.
HISTORICAL_ALIASES: dict[str, str] = {
    "bench": "barbell bench press",
    "bench press": "barbell bench press",
    "pull down": "lat pulldown",
    "pulldown machine": "lat pulldown",
    "tricep ohp": "dumbbell overhead tricep extension",
    "tricep overhead press": "dumbbell overhead tricep extension",
    "tricep cable overhead press": "cable overhead tricep extension",
    "tricep press": "cable tricep pushdown",
    "bulgarian": "bulgarian split squat",
    "romanian": "barbell romanian deadlift",
    "romanian bosu": "single leg bosu romanian deadlift",
    "shoulder press": "dumbbell shoulder press",
    "incline dumbbell bench": "incline dumbbell press",
    "dumbbell incline press": "incline dumbbell press",
    "incline bench": "incline dumbbell press",
    "standing calf raise": "calf raise",
    "hang": "dead hang",
    "kettlebell twist": "kettlebell russian twist",
    "deadlift": "barbell deadlift",
    "decline bench": "decline barbell bench press",
    "dumbbell clean press": "dumbbell clean and press",
    "kettlebell clean press": "kettlebell clean and press",
}


@dataclass(frozen=True)
class ImportSummary:
    """How many rows of each kind the import wrote."""

    exercises: int
    aliases: int
    workouts: int
    sets: int
    body_metrics: int
    cardio_sessions: int


def to_utc(value: str) -> str:
    """Normalise a v1 timestamp to UTC ISO-8601 with seconds precision."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def import_v1(source: sqlite3.Connection, target: sqlite3.Connection) -> ImportSummary:
    """Replace everything previously imported from v1 with the current v1 data."""
    with target:
        delete_source(target, SOURCE)
        exercise_ids = _import_exercises(source, target)
        aliases = _import_aliases(target)
        workouts, sets = _import_workouts(source, target, exercise_ids)
        metrics = _import_body_metrics(source, target)
        cardio = _import_cardio(source, target)
    return ImportSummary(len(exercise_ids), aliases, workouts, sets, metrics, cardio)


@dataclass(frozen=True)
class Changes:
    """Rows a re-import would add and remove, each as one readable line."""

    added: list[str]
    removed: list[str]


@dataclass(frozen=True)
class ImportPreview:
    """What re-importing would write, and how that differs from the last import."""

    summary: ImportSummary
    workouts: Changes
    sets: Changes
    body_metrics: Changes
    cardio_sessions: Changes
    new_exercises: list[str]


def preview_import(source: sqlite3.Connection, target: sqlite3.Connection) -> ImportPreview:
    """Re-import into a copy of ``target`` held in memory, and compare.

    ``target`` is only read, and may be a read-only connection.
    """
    with closing(connect(":memory:")) as scratch:
        target.backup(scratch)
        migrate(scratch)
        before, names = source_rows(scratch, SOURCE), exercise_names(scratch)
        summary = import_v1(source, scratch)
        after = source_rows(scratch, SOURCE)
        new_exercises = sorted(exercise_names(scratch) - names)
    return ImportPreview(
        summary,
        _changes(before.workouts, after.workouts),
        _changes(before.sets, after.sets),
        _changes(before.body_metrics, after.body_metrics),
        _changes(before.cardio_sessions, after.cardio_sessions),
        new_exercises,
    )


def _changes(before: list[Row], after: list[Row]) -> Changes:
    old, new = Counter(map(_line, before)), Counter(map(_line, after))
    return Changes(sorted((new - old).elements()), sorted((old - new).elements()))


def _line(row: Row) -> str:
    return " | ".join("-" if value is None else str(value) for value in row)


def _import_exercises(source: sqlite3.Connection, target: sqlite3.Connection) -> dict[int, int]:
    """Upsert v1 strength movements; map v1 movement id to exercise id."""
    ids: dict[int, int] = {}
    for row in source.execute(
        """
        SELECT id, name, display_name, equipment, muscle_groups, default_unit
        FROM movements WHERE modality = 'strength' ORDER BY id
        """
    ):
        spec = ExerciseSpec(
            name=row[1],
            display_name=row[2],
            equipment=row[3] or Equipment.BODYWEIGHT.value,  # none means bodyweight
            muscle_groups=row[4],
            measure=Measure.SECONDS if row[5] == "s" else Measure.REPS,
        )
        ids[row[0]] = upsert_exercise(target, spec)
    return ids


def _import_aliases(target: sqlite3.Connection) -> int:
    """Seed the historical names whose target exercise exists."""
    written = 0
    for alias, name in HISTORICAL_ALIASES.items():
        exercise_id = resolve(target, name)
        if exercise_id is not None:
            add_alias(target, alias, exercise_id)
            written += 1
    return written


def _import_workouts(
    source: sqlite3.Connection, target: sqlite3.Connection, exercise_ids: dict[int, int]
) -> tuple[int, int]:
    """Copy strength sessions and their sets; return (workouts, sets) written."""
    workout_ids: dict[int, int] = {}
    for row in source.execute(
        """
        SELECT id, started_at, ended_at, notes FROM sessions
        WHERE kind = 'strength' ORDER BY started_at, id
        """
    ):
        ended = None if row[2] is None else to_utc(row[2])
        record = WorkoutRecord(to_utc(row[1]), ended, row[3], SOURCE)
        workout_ids[row[0]] = insert_workout(target, record)
    sets = 0
    for row in source.execute(
        """
        SELECT i.session_id, i.movement_id, i.position, e.position, e.reps, e.weight_kg,
            e.duration_s, e.rpe, e.notes
        FROM efforts e
        JOIN session_items i ON i.id = e.session_item_id
        JOIN sessions s ON s.id = i.session_id
        WHERE s.kind = 'strength' ORDER BY i.session_id, i.position, e.position
        """
    ):
        insert_set(
            target,
            SetRecord(
                workout_id=workout_ids[row[0]],
                exercise_id=exercise_ids[row[1]],
                exercise_position=row[2],
                set_number=row[3],
                reps=row[4],
                load_kg=row[5],
                duration_s=row[6],
                rpe=row[7],
                notes=row[8],
            ),
        )
        sets += 1
    return len(workout_ids), sets


def _import_body_metrics(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    rows = source.execute(
        """SELECT date, metric, value, unit FROM body_metrics ORDER BY date, id"""
    ).fetchall()
    for row in rows:
        insert_body_metric(target, BodyMetricRecord(to_utc(row[0]), row[1], row[2], row[3], SOURCE))
    return len(rows)


def _import_cardio(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    rows = source.execute(
        """
        SELECT s.started_at, m.display_name, e.duration_s, e.distance_m, s.notes
        FROM sessions s
        JOIN session_items i ON i.session_id = s.id
        JOIN movements m ON m.id = i.movement_id
        JOIN efforts e ON e.session_item_id = i.id
        WHERE s.kind = 'cardio' ORDER BY s.started_at, e.id
        """
    ).fetchall()
    for row in rows:
        insert_cardio(target, CardioRecord(to_utc(row[0]), row[1], row[2], row[3], row[4], SOURCE))
    return len(rows)
