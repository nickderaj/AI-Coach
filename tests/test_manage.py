"""``python -m trainer.manage`` command line."""

import runpy
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
    assert out.startswith("usage: python -m trainer.manage [-h] {migrate,import-v1} ...\n")
    assert "database administration commands." in out
    lines = [" ".join(line.split()) for line in out.splitlines()]
    assert "migrate create or upgrade the database schema" in lines
    assert "import-v1 (re)import history from a v1 gym database copy" in lines


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["migrate"], "--database"),
        (["import-v1", "--database", "x"], "--source"),
        (["import-v1", "--source", "x"], "--database"),
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
