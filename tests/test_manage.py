"""``python -m trainer.manage`` command line."""

import hashlib
import runpy
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from trainer.manage import main
from trainer.storage.database import MIGRATIONS, connect, schema_version


def test_migrate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "trainer.db"

    assert main(["migrate", "--database", str(database)]) == 0

    assert capsys.readouterr().out == f"schema at v{len(MIGRATIONS)}\n"
    with closing(connect(database)) as conn:
        assert schema_version(conn) == len(MIGRATIONS)


def test_import_v1(tmp_path: Path, v1_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "fresh.db"

    assert main(["import-v1", "--source", str(v1_path), "--database", str(database)]) == 0

    assert capsys.readouterr().out == (
        "imported from v1: 4 exercises, 5 aliases, 2 workouts, 5 sets, 1 body metrics, "
        "1 cardio sessions\n"
    )
    with closing(connect(database)) as conn:
        assert schema_version(conn) == len(MIGRATIONS)


def test_import_v1_leaves_the_source_untouched(tmp_path: Path, v1_path: Path) -> None:
    before = hashlib.sha256(v1_path.read_bytes()).hexdigest()
    siblings = sorted(child.name for child in v1_path.parent.iterdir())

    assert main(["import-v1", "--source", str(v1_path), "--database", str(tmp_path / "t.db")]) == 0

    assert hashlib.sha256(v1_path.read_bytes()).hexdigest() == before
    with closing(sqlite3.connect(f"{v1_path.as_uri()}?mode=ro", uri=True)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert sorted(child.name for child in v1_path.parent.iterdir()) == sorted([*siblings, "t.db"])


def test_import_v1_accepts_a_read_only_source(tmp_path: Path, v1_path: Path) -> None:
    v1_path.chmod(0o444)

    assert main(["import-v1", "--source", str(v1_path), "--database", str(tmp_path / "t.db")]) == 0


@pytest.mark.parametrize("via_symlink", [False, True])
def test_import_v1_refuses_to_import_into_itself(
    tmp_path: Path, v1_path: Path, capsys: pytest.CaptureFixture[str], *, via_symlink: bool
) -> None:
    target = v1_path
    if via_symlink:
        target = tmp_path / "alias.db"
        target.symlink_to(v1_path)
    before = hashlib.sha256(v1_path.read_bytes()).hexdigest()

    assert main(["import-v1", "--source", str(v1_path), "--database", str(target)]) == 1

    assert capsys.readouterr().err == f"refusing to import {v1_path} into itself\n"
    assert hashlib.sha256(v1_path.read_bytes()).hexdigest() == before


def test_import_v1_refuses_a_missing_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.db"

    assert main(["import-v1", "--source", str(missing), "--database", str(tmp_path / "t.db")]) == 1

    assert capsys.readouterr().err == f"v1 database not found: {missing}\n"
    assert not missing.exists()
    assert not (tmp_path / "t.db").exists()


def test_help(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit):
        main(["--help"])

    out = capsys.readouterr().out
    assert out.startswith(
        "usage: python -m trainer.manage [-h] {migrate,import-v1,seed-exercises} ...\n"
    )
    assert "database administration commands." in out
    lines = [" ".join(line.split()) for line in out.splitlines()]
    assert "migrate create or upgrade the database schema" in lines
    assert "import-v1 (re)import history from a v1 gym database copy" in lines
    assert "seed-exercises add common exercises the catalogue does not have yet" in lines


def test_seed_exercises_help(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit):
        main(["seed-exercises", "--help"])

    lines = [" ".join(line.split()) for line in capsys.readouterr().out.splitlines()]
    assert "--dry-run list them without adding" in lines


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["migrate"], "--database"),
        (["import-v1", "--database", "x"], "--source"),
        (["import-v1", "--source", "x"], "--database"),
        (["seed-exercises"], "--database"),
    ],
)
def test_options_are_required(
    argv: list[str], missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(argv)

    assert exited.value.code == 2
    assert f"the following arguments are required: {missing}" in capsys.readouterr().err


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([])

    assert "required: command" in capsys.readouterr().err


def test_module_entry_point(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv", ["trainer.manage", "migrate", "--database", str(tmp_path / "t.db")]
    )
    monkeypatch.delitem(sys.modules, "trainer.manage", raising=False)

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("trainer.manage", run_name="__main__")

    assert exited.value.code == 0


def test_seed_exercises(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = str(tmp_path / "t.db")

    assert main(["seed-exercises", "--database", database, "--dry-run"]) == 0
    dry = capsys.readouterr().out.splitlines()
    assert main(["seed-exercises", "--database", database]) == 0
    real = capsys.readouterr().out.splitlines()
    assert main(["seed-exercises", "--database", database]) == 0
    again = capsys.readouterr().out

    count = len(dry) - 1
    assert dry[0] == f"would add {count} common exercises"
    assert "  Barbell Back Squat (barbell)" in dry
    assert real == [f"added {count} common exercises", *dry[1:]]
    assert again == "added 0 common exercises\n"
