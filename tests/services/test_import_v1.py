"""Importing history from the v1 gym bot."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from trainer.services.import_v1 import (
    HISTORICAL_ALIASES,
    Changes,
    ImportSummary,
    import_v1,
    preview_import,
    to_utc,
)
from trainer.storage.catalogue import resolve
from trainer.storage.database import (
    MIGRATIONS,
    connect,
    connect_readonly,
    migrate,
    schema_version,
)

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


def test_a_movement_without_equipment_is_bodyweight(
    v1: sqlite3.Connection, db: sqlite3.Connection
) -> None:
    v1.execute("UPDATE movements SET equipment = NULL WHERE name = 'pullup'")

    import_v1(v1, db)

    row = db.execute("SELECT equipment FROM exercises WHERE name = 'pullup'").fetchone()
    assert tuple(row) == ("bodyweight",)


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


# ---------------------------------------------------------------- dry run


def line(*values: object) -> str:
    """A row as the preview writes it: JSON values, so NULL and "-" differ."""
    return " | ".join(json.dumps(value) for value in values)


BENCH = ("barbell bench press", "Barbell Bench Press", "barbell", "chest,triceps", "reps", None)


def test_a_preview_against_an_empty_log_adds_everything(
    v1: sqlite3.Connection, db: sqlite3.Connection
) -> None:
    preview = preview_import(v1, db)

    assert preview.summary == EXPECTED
    assert preview.workouts == Changes(
        [
            line("2026-07-09T10:47:23+00:00", None, "first", 3),
            line("2026-08-17T11:36:06+00:00", "2026-08-17T12:09:54+00:00", "good", 2),
        ],
        [],
    )
    assert preview.sets.added == [
        line("2026-07-09T10:47:23+00:00", "barbell bench press", 1, 1, 8, 60.0, None, None, None),
        line("2026-07-09T10:47:23+00:00", "barbell bench press", 1, 2, 6, 70.0, None, 8, "grindy"),
        line("2026-07-09T10:47:23+00:00", "dead hang", 2, 1, None, None, 50.0, None, None),
        line("2026-08-17T11:36:06+00:00", "lat pulldown", 1, 1, 12, 50.0, None, None, None),
        line("2026-08-17T11:36:06+00:00", "pullup", 2, 1, 8, None, None, None, None),
    ]
    assert preview.body_metrics == Changes(
        [line("2026-07-08T10:16:29+00:00", "weight_kg", 64.25, "kg")], []
    )
    assert preview.cardio_sessions == Changes(
        [line("2026-08-06T14:50:50+00:00", "Pilates", 3600.0, 1200.0, "reformer")], []
    )
    assert preview.exercises.added[0] == line(*BENCH)
    assert len(preview.exercises.added) == 4
    assert preview.exercises.removed == []
    assert preview.aliases.added == [
        line("bench press", "barbell bench press"),  # sorted as written: " before '"'
        line("bench", "barbell bench press"),
        line("hang", "dead hang"),
        line("pull down", "lat pulldown"),
        line("pulldown machine", "lat pulldown"),
    ]
    # Nothing was written.
    assert db.execute("SELECT count(*) FROM exercises").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM workouts").fetchone()[0] == 0
    assert not db.in_transaction


def test_a_preview_after_the_same_import_changes_nothing(
    v1: sqlite3.Connection, imported: sqlite3.Connection
) -> None:
    preview = preview_import(v1, imported)

    assert preview.summary == EXPECTED
    for changes in (
        preview.workouts,
        preview.sets,
        preview.body_metrics,
        preview.cardio_sessions,
        preview.exercises,
        preview.aliases,
    ):
        assert changes == Changes([], [])


def test_a_preview_shows_what_v1_gained_and_lost(
    v1: sqlite3.Connection, imported: sqlite3.Connection
) -> None:
    v1.executescript(
        """
        INSERT INTO movements VALUES
            (70, 'goblet squat', 'Goblet Squat', 'strength', 'legs', 'kettlebell', 'kg');
        INSERT INTO sessions VALUES (4, '2026-09-29T18:00:00+01:00', NULL, 'strength', NULL);
        INSERT INTO session_items VALUES (40, 4, 1, 70);
        INSERT INTO efforts VALUES (400, 40, 1, 10, 16.0, NULL, NULL, NULL, NULL);
        UPDATE efforts SET reps = 9 WHERE id = 100;
        DELETE FROM body_metrics;
        """
    )

    preview = preview_import(v1, imported)

    assert preview.workouts.added == [line("2026-09-29T17:00:00+00:00", None, None, 1)]
    assert preview.workouts.removed == []
    assert preview.sets.added == [
        line("2026-07-09T10:47:23+00:00", "barbell bench press", 1, 1, 9, 60.0, None, None, None),
        line("2026-09-29T17:00:00+00:00", "goblet squat", 1, 1, 10, 16.0, None, None, None),
    ]
    assert preview.sets.removed == [
        line("2026-07-09T10:47:23+00:00", "barbell bench press", 1, 1, 8, 60.0, None, None, None)
    ]
    assert preview.body_metrics == Changes(
        [], [line("2026-07-08T10:16:29+00:00", "weight_kg", 64.25, "kg")]
    )
    assert preview.exercises == Changes(
        [line("goblet squat", "Goblet Squat", "kettlebell", "legs", "reps", None)], []
    )
    assert imported.execute("SELECT count(*) FROM workouts").fetchone()[0] == 2


def test_a_preview_tells_null_from_text_that_reads_like_it(
    v1: sqlite3.Connection, imported: sqlite3.Connection
) -> None:
    # From review: rows formatted before comparing hid a NULL becoming "-".
    imported.execute("UPDATE workouts SET notes = '-' WHERE notes = 'first'")
    imported.commit()
    v1.execute("UPDATE sessions SET notes = NULL WHERE id = 1")

    preview = preview_import(v1, imported)

    assert preview.workouts == Changes(
        [line("2026-07-09T10:47:23+00:00", None, None, 3)],
        [line("2026-07-09T10:47:23+00:00", None, "-", 3)],
    )


def test_a_preview_keeps_fields_apart(v1: sqlite3.Connection, imported: sqlite3.Connection) -> None:
    # " | " inside a value cannot pass for a field boundary.
    imported.execute("UPDATE workouts SET notes = 'good | x' WHERE notes = 'good'")
    imported.commit()

    preview = preview_import(v1, imported)

    assert preview.workouts.removed == [
        line("2026-08-17T11:36:06+00:00", "2026-08-17T12:09:54+00:00", "good | x", 2)
    ]


def test_a_preview_shows_catalogue_details_the_import_would_overwrite(
    v1: sqlite3.Connection, imported: sqlite3.Connection
) -> None:
    # From review: the import updates every v1 exercise's details and retargets
    # its historical aliases, which the log rows alone do not show.
    imported.execute(
        "UPDATE exercises SET display_name = 'Bench', load_increment_kg = 1.25 "
        "WHERE name = 'barbell bench press'"
    )
    imported.execute(
        "UPDATE exercise_aliases SET exercise_id = "
        "(SELECT id FROM exercises WHERE name = 'pullup') WHERE alias = 'bench'"
    )
    imported.commit()

    preview = preview_import(v1, imported)

    assert preview.exercises == Changes(
        [
            line(
                "barbell bench press",
                "Barbell Bench Press",
                "barbell",
                "chest,triceps",
                "reps",
                1.25,
            )
        ],
        [line("barbell bench press", "Bench", "barbell", "chest,triceps", "reps", 1.25)],
    )
    assert preview.aliases == Changes(
        [line("bench", "barbell bench press")], [line("bench", "pullup")]
    )
    assert preview.workouts == Changes([], [])


def test_a_preview_counts_repeated_rows(v1: sqlite3.Connection, db: sqlite3.Connection) -> None:
    v1.execute(
        "INSERT INTO body_metrics VALUES (2, '2026-07-08 10:16:29', 'weight_kg', 64.25, 'kg')"
    )

    preview = preview_import(v1, db)

    assert (
        preview.body_metrics.added
        == [line("2026-07-08T10:16:29+00:00", "weight_kg", 64.25, "kg")] * 2
    )


def test_a_preview_reads_a_read_only_log(v1: sqlite3.Connection, tmp_path: Path) -> None:
    path = tmp_path / "trainer.db"
    with closing(connect(path)) as conn:
        migrate(conn)
        import_v1(v1, conn)
    before = path.read_bytes()

    with closing(connect_readonly(path)) as target:
        preview = preview_import(v1, target)

    assert preview.workouts == Changes([], [])
    assert path.read_bytes() == before


def test_a_preview_brings_an_older_log_up_to_date_in_memory_only(
    v1: sqlite3.Connection, tmp_path: Path
) -> None:
    path = tmp_path / "old.db"
    with closing(connect(path)) as conn:
        for sql in MIGRATIONS[:5]:
            conn.executescript(sql)
        conn.execute("PRAGMA user_version = 5")

    with closing(connect_readonly(path)) as target:
        assert preview_import(v1, target).summary == EXPECTED

    with closing(connect_readonly(path)) as target:
        assert schema_version(target) == 5


def test_a_preview_leaves_no_file_behind(
    v1: sqlite3.Connection, db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    preview_import(v1, db)

    assert list(work.iterdir()) == []  # the copy was held in memory
