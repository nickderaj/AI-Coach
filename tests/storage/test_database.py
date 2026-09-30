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


@pytest.mark.parametrize(
    "statement",
    [
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
