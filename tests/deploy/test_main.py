"""``python -m trainer.deploy`` command line."""

import runpy
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trainer.deploy.__main__ import main

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "local.env.example"


def test_render_writes_the_bundle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "bundle"

    assert main(["render", "--env", str(EXAMPLE), "--out", str(out)]) == 0

    assert (out / "install.env").is_file()
    assert sorted(path.name for path in (out / "systemd").iterdir()) == [
        "trainer-api.service",
        "trainer-backup.service",
        "trainer-backup.timer",
    ]
    assert capsys.readouterr().out.splitlines() == [
        f"rendered {out}/systemd/trainer-api.service",
        f"rendered {out}/systemd/trainer-backup.service",
        f"rendered {out}/systemd/trainer-backup.timer",
        f"rendered {out}/install.env",
    ]


def test_render_reports_an_invalid_env(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = tmp_path / "local.env"
    env.write_text("TRAINER_USER=trainer\n")

    assert main(["render", "--env", str(env), "--out", str(tmp_path / "out")]) == 1

    assert capsys.readouterr().err.startswith(f"{env}: missing TRAINER_DATA_DIR, ")
    assert not (tmp_path / "out").exists()


def test_backup_without_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["backup", "--data-dir", str(tmp_path), "--keep", "3"]) == 0

    assert capsys.readouterr().out == "no database yet; nothing to do\n"


def test_backup_with_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with closing(sqlite3.connect(tmp_path / "trainer.db")) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")

    assert main(["backup", "--data-dir", str(tmp_path), "--keep", "3"]) == 0

    written = next((tmp_path / "backups").iterdir())
    assert capsys.readouterr().out == f"backed up to {written}\n"


def test_help_describes_the_commands(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")  # argparse wraps help at the terminal width

    with pytest.raises(SystemExit):
        main(["--help"])

    out = capsys.readouterr().out
    assert out.startswith("usage: python -m trainer.deploy [-h] {render,backup} ...\n")
    assert "render the install bundle, or run a backup." in out
    lines = [line.strip() for line in out.splitlines()]
    assert "render         validate local.env and render the bundle" in lines
    assert "backup         back up the database and rotate" in lines


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["render", "--out", "x"], "--env"),
        (["render", "--env", "x"], "--out"),
        (["backup", "--keep", "1"], "--data-dir"),
        (["backup", "--data-dir", "x"], "--keep"),
    ],
)
def test_every_option_is_required(
    argv: list[str], missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(argv)

    assert exited.value.code == 2
    assert f"the following arguments are required: {missing}" in capsys.readouterr().err


@pytest.fixture
def far_east_timezone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "Etc/GMT-14")  # UTC+14: local and UTC dates always differ
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.usefixtures("far_east_timezone")
def test_backups_are_named_in_utc(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / "trainer.db")) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")

    main(["backup", "--data-dir", str(tmp_path), "--keep", "3"])

    name = next((tmp_path / "backups").iterdir()).name
    stamp = datetime.strptime(name, "trainer-%Y%m%dT%H%M%SZ.db").replace(tzinfo=UTC)
    assert abs(datetime.now(UTC) - stamp) < timedelta(minutes=1)


def test_a_subcommand_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        main([])

    assert exited.value.code == 2
    assert "required: command" in capsys.readouterr().err


def test_module_entry_point_exits_with_main_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["trainer.deploy", "backup", "--data-dir", str(tmp_path), "--keep", "1"]
    )
    monkeypatch.delitem(sys.modules, "trainer.deploy.__main__", raising=False)

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("trainer.deploy", run_name="__main__")

    assert exited.value.code == 0
