"""Importing history from the v1 gym bot."""

import sqlite3

import pytest

from trainer.services.import_v1 import (
    HISTORICAL_ALIASES,
    ImportSummary,
    import_v1,
    to_utc,
)
from trainer.storage.catalogue import resolve

# Timestamps must not depend on the host's timezone (CI runs in UTC).
pytestmark = pytest.mark.usefixtures("far_east_timezone")

EXPECTED = ImportSummary(
    exercises=4, aliases=5, workouts=2, sets=5, body_metrics=1, cardio_sessions=1
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-07-09 10:47:23", "2026-07-09T10:47:23+00:00"),
        ("2026-08-17T12:36:06.923574+01:00", "2026-08-17T11:36:06+00:00"),
        ("2026-08-17T00:30:00+01:00", "2026-08-16T23:30:00+00:00"),
    ],
)
def test_to_utc(value: str, expected: str) -> None:
    assert to_utc(value) == expected


def test_import_summary(v1: sqlite3.Connection, db: sqlite3.Connection) -> None:
    assert import_v1(v1, db) == EXPECTED


def test_exercises_keep_identity_and_measure(
    v1: sqlite3.Connection, db: sqlite3.Connection
) -> None:
    import_v1(v1, db)

    assert [
        tuple(row)
        for row in db.execute(
            "SELECT name, display_name, equipment, muscle_groups, measure "
            "FROM exercises ORDER BY name"
        )
    ] == [
        ("barbell bench press", "Barbell Bench Press", "barbell", "chest,triceps", "reps"),
        ("dead hang", "Dead Hang", "bodyweight", "grip", "seconds"),
        ("lat pulldown", "Lat Pulldown", "cable", "back,biceps", "reps"),
        ("pullup", "Pull-up", "bodyweight", "back,biceps", "reps"),
    ]


def test_historical_aliases_resolve_when_their_exercise_exists(
    v1: sqlite3.Connection, db: sqlite3.Connection
) -> None:
    import_v1(v1, db)

    bench = resolve(db, "barbell bench press")
    assert bench is not None
    assert resolve(db, "bench") == bench
    assert resolve(db, "bench press") == bench
    assert resolve(db, "pull down") == resolve(db, "lat pulldown")
    assert resolve(db, "hang") == resolve(db, "dead hang")
    assert resolve(db, "tricep press") is None  # its exercise is not in this v1 fixture


def test_workouts_are_utc_and_ordered(v1: sqlite3.Connection, db: sqlite3.Connection) -> None:
    import_v1(v1, db)

    assert [
        tuple(row)
        for row in db.execute(
            "SELECT started_at, ended_at, notes, source FROM workouts ORDER BY id"
        )
    ] == [
        ("2026-07-09T10:47:23+00:00", None, "first", "v1"),
        ("2026-08-17T11:36:06+00:00", "2026-08-17T12:09:54+00:00", "good", "v1"),
    ]


def test_sets_carry_position_load_time_and_notes(
    v1: sqlite3.Connection, db: sqlite3.Connection
) -> None:
    import_v1(v1, db)

    assert [
        tuple(row)
        for row in db.execute(
            "SELECT e.name, s.exercise_position, s.set_number, s.reps, s.load_kg, s.duration_s, "
            "s.rpe, s.notes FROM workout_sets s JOIN exercises e ON e.id = s.exercise_id "
            "JOIN workouts w ON w.id = s.workout_id ORDER BY w.started_at, s.exercise_position, "
            "s.set_number"
        )
    ] == [
        ("barbell bench press", 1, 1, 8, 60.0, None, None, None),
        ("barbell bench press", 1, 2, 6, 70.0, None, 8, "grindy"),
        ("dead hang", 2, 1, None, None, 50.0, None, None),
        ("lat pulldown", 1, 1, 12, 50.0, None, None, None),
        ("pullup", 2, 1, 8, None, None, None, None),
    ]


def test_body_metrics_and_cardio(v1: sqlite3.Connection, db: sqlite3.Connection) -> None:
    import_v1(v1, db)

    assert tuple(
        db.execute("SELECT measured_at, metric, value, unit, source FROM body_metrics").fetchone()
    ) == (
        "2026-07-08T10:16:29+00:00",
        "weight_kg",
        64.25,
        "kg",
        "v1",
    )
    assert tuple(
        db.execute(
            "SELECT started_at, activity, duration_s, distance_m, notes, source "
            "FROM cardio_sessions"
        ).fetchone()
    ) == ("2026-08-06T14:50:50+00:00", "Pilates", 3600.0, 1200.0, "reformer", "v1")


def test_reimport_replaces_rather_than_duplicates(
    v1: sqlite3.Connection, db: sqlite3.Connection
) -> None:
    import_v1(v1, db)
    ids = dict(db.execute("SELECT name, id FROM exercises").fetchall())

    assert import_v1(v1, db) == EXPECTED

    assert dict(db.execute("SELECT name, id FROM exercises").fetchall()) == ids
    assert db.execute("SELECT count(*) FROM workout_sets").fetchone()[0] == 5
    assert db.execute("SELECT count(*) FROM workouts").fetchone()[0] == 2


def test_other_sources_survive_a_reimport(v1: sqlite3.Connection, db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO workouts (started_at, source) VALUES ('2026-09-30T08:00:00+00:00', 'app')"
    )
    db.commit()

    import_v1(v1, db)

    assert db.execute("SELECT count(*) FROM workouts WHERE source = 'app'").fetchone()[0] == 1


def test_a_failed_import_changes_nothing(v1: sqlite3.Connection, db: sqlite3.Connection) -> None:
    import_v1(v1, db)
    v1.execute("INSERT INTO session_items VALUES (99, 1, 3, 12345)")  # unknown movement
    v1.execute("INSERT INTO efforts (id, session_item_id, position, reps) VALUES (999, 99, 1, 5)")

    with pytest.raises(KeyError):
        import_v1(v1, db)

    assert db.execute("SELECT count(*) FROM workout_sets").fetchone()[0] == 5
    assert not db.in_transaction


def test_every_historical_alias_targets_a_distinct_name() -> None:
    assert set(HISTORICAL_ALIASES).isdisjoint(HISTORICAL_ALIASES.values())
    assert all(alias == alias.lower().strip() for alias in HISTORICAL_ALIASES)
