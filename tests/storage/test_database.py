"""Connection settings and schema migrations."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from trainer.storage import database
from trainer.storage.database import (
    MIGRATIONS,
    SchemaError,
    connect,
    connect_readonly,
    migrate,
    schema_version,
    write_transaction,
)


def test_connection_enforces_foreign_keys_and_uses_wal(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1


def test_busy_timeout_is_five_seconds(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_migrate_creates_the_schema(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        assert schema_version(conn) == 0

        assert migrate(conn) == len(MIGRATIONS)

        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }
        assert tables == {
            "exercises",
            "exercise_aliases",
            "workouts",
            "workout_sets",
            "body_metrics",
            "cardio_sessions",
            "profile",
            "coach",
            "programs",
            "program_days",
            "program_blocks",
            "block_exercises",
        }


def test_migrate_is_idempotent(db: sqlite3.Connection) -> None:
    assert migrate(db) == len(MIGRATIONS)


def test_newer_schema_is_refused(db: sqlite3.Connection) -> None:
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")

    newer, current = len(MIGRATIONS) + 1, len(MIGRATIONS)
    expected = rf"^database schema v{newer} is newer than this app \(v{current}\)$"
    with pytest.raises(SchemaError, match=expected):
        migrate(db)


def test_a_failing_migration_leaves_no_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "MIGRATIONS", ("CREATE TABLE a (x); CREATE TABLE a (x);",))

    with closing(connect(tmp_path / "t.db")) as conn:
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn)

        assert schema_version(conn) == 0
        assert conn.execute("SELECT count(*) FROM sqlite_schema").fetchone()[0] == 0
        assert not conn.in_transaction


def test_migrations_apply_in_order_from_the_current_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "MIGRATIONS", ("CREATE TABLE a (x);", "CREATE TABLE b (x);"))
    with closing(connect(tmp_path / "t.db")) as conn:
        conn.execute("CREATE TABLE a (x)")
        conn.execute("PRAGMA user_version = 1")

        assert migrate(conn) == 2

        assert conn.execute("SELECT count(*) FROM b").fetchone()[0] == 0


def test_v4_gives_exercises_without_equipment_bodyweight(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        for sql in MIGRATIONS[:3]:
            conn.executescript(sql)
        conn.execute("PRAGMA user_version = 3")
        conn.executemany(
            "INSERT INTO exercises (name, display_name, equipment, measure) VALUES (?, ?, ?, ?)",
            [("plank", "Plank", None, "seconds"), ("row", "Row", "cable", "reps")],
        )
        conn.commit()

        assert migrate(conn) == len(MIGRATIONS)

        rows = conn.execute("SELECT name, equipment FROM exercises ORDER BY name").fetchall()
        assert [tuple(row) for row in rows] == [("plank", "bodyweight"), ("row", "cable")]


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO profile (id, bodyweight_kg) VALUES (2, 65)",  # one row only
        "INSERT INTO profile (id, bodyweight_kg) VALUES (1, 0)",
        "INSERT INTO exercises (name, display_name, measure) VALUES ('x', 'X', 'laps')",
        (
            "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number) "
            "VALUES (999, 999, 1, 1)"
        ),
    ],
)
def test_schema_rejects_invalid_rows(db: sqlite3.Connection, statement: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(statement)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("exercise_position", 0),
        ("set_number", 0),
        ("reps", -1),
        ("load_kg", -0.5),
        ("duration_s", -1),
        ("rpe", 0),
        ("rpe", 11),
    ],
)
def test_set_values_are_range_checked(db: sqlite3.Connection, column: str, value: float) -> None:
    db.execute(
        "INSERT INTO exercises (id, name, display_name, measure) VALUES (1, 'x', 'X', 'reps')"
    )
    db.execute("INSERT INTO workouts (id, started_at, source) VALUES (1, 't', 'test')")
    values = {"exercise_position": 1, "set_number": 1, column: value}
    columns = ", ".join(values)

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            f"INSERT INTO workout_sets (workout_id, exercise_id, {columns}) "  # noqa: S608  # why: column names come from the parametrize list
            f"VALUES (1, 1, {', '.join('?' * len(values))})",
            tuple(values.values()),
        )


PROGRAM = """
    INSERT INTO exercises (id, name, display_name, equipment, measure)
        VALUES (1, 'bench', 'Bench', 'barbell', 'reps');
    INSERT INTO programs (id, name, training_weeks, status, created_at)
        VALUES (1, 'Upper/Lower', 6, 'active', 't');
    INSERT INTO program_days (id, program_id, position, name) VALUES (1, 1, 1, 'Upper A');
    INSERT INTO program_blocks (id, day_id, position, rest_s) VALUES (1, 1, 1, 90);
    INSERT INTO block_exercises (id, block_id, position, exercise_id, sets, rep_min, rep_max)
        VALUES (1, 1, 1, 1, 3, 8, 10);
    INSERT INTO workouts (id, started_at, source) VALUES (1, 't', 'app');
"""


def test_v6_keeps_existing_rows_outside_any_program(tmp_path: Path) -> None:
    with closing(connect(tmp_path / "t.db")) as conn:
        for sql in MIGRATIONS[:5]:
            conn.executescript(sql)
        conn.execute("PRAGMA user_version = 5")
        conn.executescript(
            """
            INSERT INTO exercises (id, name, display_name, equipment, measure)
                VALUES (1, 'bench', 'Bench', 'barbell', 'reps');
            INSERT INTO workouts (id, started_at, source) VALUES (1, 't', 'app');
            INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number)
                VALUES (1, 1, 1, 1);
            """
        )

        assert migrate(conn) == len(MIGRATIONS)

        row = conn.execute(
            "SELECT e.load_increment_kg, w.program_day_id, w.program_week, s.block_exercise_id "
            "FROM workout_sets s JOIN workouts w ON w.id = s.workout_id "
            "JOIN exercises e ON e.id = s.exercise_id"
        ).fetchone()
        assert tuple(row) == (None, None, None, None)


@pytest.fixture
def program(db: sqlite3.Connection) -> sqlite3.Connection:
    """A database with one active program of one day, block and exercise, and a workout."""
    db.executescript(PROGRAM)
    return db


def test_a_workout_and_its_sets_link_to_a_program(program: sqlite3.Connection) -> None:
    program.execute("UPDATE workouts SET program_day_id = 1, program_week = 7")
    program.execute(
        "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, "
        "block_exercise_id) VALUES (1, 1, 1, 1, 1)"
    )
    program.execute("UPDATE exercises SET load_increment_kg = 1.25")

    assert program.execute("SELECT count(*) FROM workout_sets").fetchone()[0] == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE programs SET name = ''",
        "UPDATE programs SET training_weeks = 0",
        "UPDATE programs SET status = 'done'",
        # One active and one proposed program at most.
        (
            "INSERT INTO programs (name, training_weeks, status, created_at) "
            "VALUES ('Again', 6, 'active', 't')"
        ),
        "UPDATE program_days SET position = 0",
        "UPDATE program_days SET name = ''",
        "INSERT INTO program_days (program_id, position, name) VALUES (1, 1, 'Same place')",
        "UPDATE program_blocks SET position = 0",
        "UPDATE program_blocks SET rest_s = -1",
        "UPDATE program_blocks SET rest_s = 601",
        "INSERT INTO program_blocks (day_id, position, rest_s) VALUES (1, 1, 60)",
        "UPDATE block_exercises SET position = 0",
        "UPDATE block_exercises SET sets = 0",
        "UPDATE block_exercises SET sets = 11",
        "UPDATE block_exercises SET rep_min = 0",
        "UPDATE block_exercises SET rep_max = 7",
        "UPDATE block_exercises SET start_load_kg = -0.5",
        "UPDATE block_exercises SET exercise_id = 99",
        (
            "INSERT INTO block_exercises (block_id, position, exercise_id, sets, rep_min, rep_max) "
            "VALUES (1, 1, 1, 3, 8, 10)"
        ),
        "UPDATE exercises SET load_increment_kg = 0",
        "UPDATE workouts SET program_day_id = 99, program_week = 1",
        "UPDATE workouts SET program_day_id = 1",  # a day needs its week
        "UPDATE workouts SET program_week = 1",  # and a week its day
        "UPDATE workouts SET program_day_id = 1, program_week = 0",
        (
            "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, "
            "block_exercise_id) VALUES (1, 1, 1, 1, 99)"
        ),
        # A program trained from cannot be deleted.
        "UPDATE workouts SET program_day_id = 1, program_week = 1; DELETE FROM programs",
    ],
)
def test_programs_reject_invalid_rows(program: sqlite3.Connection, statement: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        program.executescript(statement)


def test_a_proposed_program_sits_beside_the_active_one(program: sqlite3.Connection) -> None:
    program.execute(
        "INSERT INTO programs (name, training_weeks, status, created_at) "
        "VALUES ('Next', 6, 'proposed', 't')"
    )
    program.execute(
        "INSERT INTO programs (name, training_weeks, status, created_at) "
        "VALUES ('Old', 6, 'archived', 't'), ('Older', 6, 'archived', 't')"
    )

    assert program.execute("SELECT count(*) FROM programs").fetchone()[0] == 4


def test_deleting_an_untrained_program_removes_its_days(program: sqlite3.Connection) -> None:
    program.execute("DELETE FROM programs")

    for table in ("program_days", "program_blocks", "block_exercises"):
        assert program.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0  # noqa: S608  # why: table names are the literals above


def plain_database(path: Path) -> Path:
    """A rollback-journal (non-WAL) database with one row, like an offline v1 copy."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
    return path


def fingerprint(path: Path) -> tuple[str, str, list[str]]:
    """File hash, journal mode (read without changing it) and sibling files."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    return digest, mode, sorted(child.name for child in path.parent.iterdir())


class TestReadonly:
    def test_reads_rows(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "v1.db")

        with closing(connect_readonly(path)) as conn:
            assert conn.execute("SELECT x FROM t").fetchone()["x"] == 42

    def test_leaves_the_file_untouched(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "v1.db")
        before = fingerprint(path)

        with closing(connect_readonly(path)) as conn:
            conn.execute("SELECT count(*) FROM t").fetchone()

        assert fingerprint(path) == before
        assert before[1] == "delete"

    def test_refuses_writes(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "v1.db")

        with (
            closing(connect_readonly(path)) as conn,
            pytest.raises(sqlite3.OperationalError, match="readonly database"),
        ):
            conn.execute("INSERT INTO t VALUES (1)")

    def test_never_creates_a_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.db"

        with pytest.raises(sqlite3.OperationalError, match="unable to open"):
            connect_readonly(missing)

        assert list(tmp_path.iterdir()) == []

    def test_opens_a_read_only_file(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "v1.db")
        path.chmod(0o444)

        with closing(connect_readonly(path)) as conn:
            assert conn.execute("SELECT x FROM t").fetchone()[0] == 42

    def test_handles_characters_that_need_escaping(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "a b#?%.db")

        with closing(connect_readonly(path)) as conn:
            assert conn.execute("SELECT x FROM t").fetchone()[0] == 42

    def test_relative_paths_resolve_against_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plain_database(tmp_path / "v1.db")
        monkeypatch.chdir(tmp_path)

        with closing(connect_readonly("v1.db")) as conn:
            assert conn.execute("SELECT x FROM t").fetchone()[0] == 42


class TestWriteTransaction:
    def test_commits_on_success(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "t.db")
        with closing(connect(path)) as conn:
            with write_transaction(conn):
                inside = conn.in_transaction
                conn.execute("INSERT INTO t VALUES (1)")
            after = conn.in_transaction

        assert (inside, after) == (True, False)
        with closing(sqlite3.connect(path)) as other:
            assert other.execute("SELECT count(*) FROM t").fetchone()[0] == 2

    def test_rolls_back_and_reraises_on_error(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "t.db")

        def insert_then_fail(conn: sqlite3.Connection) -> None:
            with write_transaction(conn):
                conn.execute("INSERT INTO t VALUES (1)")
                message = "boom"
                raise KeyError(message)

        with closing(connect(path)) as conn:
            with pytest.raises(KeyError, match="boom"):
                insert_then_fail(conn)

            assert not conn.in_transaction
            assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 1

    def test_holds_the_write_lock_from_the_start(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "t.db")
        with (
            closing(connect(path)) as conn,
            closing(sqlite3.connect(path, timeout=0)) as other,
            write_transaction(conn),
            # Before any write in the transaction, another writer is already blocked.
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            other.execute("BEGIN IMMEDIATE")

    def test_refuses_to_nest_inside_an_open_transaction(self, tmp_path: Path) -> None:
        path = plain_database(tmp_path / "t.db")
        with closing(connect(path)) as conn:
            conn.execute("INSERT INTO t VALUES (1)")  # opens an implicit transaction

            with (
                pytest.raises(sqlite3.OperationalError, match="within a transaction"),
                write_transaction(conn),
            ):
                pass
