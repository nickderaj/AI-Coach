"""``python -m trainer.deploy`` command line."""

import re
import runpy
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import pytest

from trainer.deploy.__main__ import main
from trainer.deploy.preflight import Entry

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "local.env.example"


def test_render_writes_the_bundle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "bundle"

    assert main(["render", "--env", str(EXAMPLE), "--out", str(out)]) == 0

    assert (out / "install.env").is_file()
    assert sorted(path.name for path in (out / "systemd").iterdir()) == [
        "trainer-api.service",
        "trainer-backup.service",
        "trainer-backup.timer",
        "trainer-coach.service",
        "trainer-memory.service",
        "trainer-memory.timer",
    ]
    assert capsys.readouterr().out.splitlines() == [
        f"rendered {out}/systemd/trainer-api.service",
        f"rendered {out}/systemd/trainer-backup.service",
        f"rendered {out}/systemd/trainer-backup.timer",
        f"rendered {out}/systemd/trainer-coach.service",
        f"rendered {out}/systemd/trainer-memory.service",
        f"rendered {out}/systemd/trainer-memory.timer",
        f"rendered {out}/install.env",
        f"rendered {out}/config.env",
    ]


def test_render_reports_an_invalid_env(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = tmp_path / "local.env"
    env.write_text("TRAINER_USER=trainer\n")

    assert main(["render", "--env", str(env), "--out", str(tmp_path / "out")]) == 1

    assert capsys.readouterr().err.startswith(f"{env}: missing TRAINER_DATA_DIR, ")
    assert not (tmp_path / "out").exists()


class RecordingHost:
    """Stands in for SystemHost: only /srv exists, owned by uid 1000."""

    owner_of_data_parent = 1000

    def account(self, name: str) -> None:  # noqa: ARG002  # why: fake of the Host protocol
        return None

    def group_name(self, gid: int) -> None:  # noqa: ARG002  # why: fake of the Host protocol
        return None

    def group_exists(self, name: str) -> bool:  # noqa: ARG002  # why: fake of the Host protocol
        return False

    def entry(self, path: PurePosixPath) -> Entry | None:
        if path == PurePosixPath("/srv"):
            return Entry(self.owner_of_data_parent, stat.S_IFDIR | 0o755)
        return None

    def names(self, path: PurePosixPath) -> list[str]:  # noqa: ARG002  # why: fake of the Host protocol
        return []


@pytest.fixture
def fake_host(monkeypatch: pytest.MonkeyPatch) -> RecordingHost:
    host = RecordingHost()
    monkeypatch.setattr("trainer.deploy.__main__.SystemHost", lambda: host)
    return host


@pytest.mark.usefixtures("fake_host")
def test_preflight_passes_on_a_safe_host(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["preflight", "--env", str(EXAMPLE), "--admin-uid", "1000"]) == 0

    assert capsys.readouterr().err == ""


@pytest.mark.usefixtures("fake_host")
def test_preflight_reports_problems(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["preflight", "--env", str(EXAMPLE), "--admin-uid", "1001"]) == 1

    assert capsys.readouterr().err == (
        "preflight: /srv is owned by uid 1000, expected one of [0, 1001]\n"
    )


def test_preflight_reports_an_invalid_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / "config.env"
    env.write_text("TRAINER_USER=root\n")

    assert main(["preflight", "--env", str(env), "--admin-uid", "0"]) == 1

    assert capsys.readouterr().err.startswith(f"{env}: missing ")


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
    assert out.startswith(
        "usage: python -m trainer.deploy [-h] {render,preflight,backup,memory-commit} ...\n"
    )
    assert "render the bundle, back up, or commit the coach's memory." in out
    lines = [" ".join(line.split()) for line in out.splitlines()]
    assert "render validate local.env and render the bundle" in lines
    assert "preflight refuse unsafe host state before install" in lines
    assert "backup back up the database and rotate" in lines
    assert "memory-commit commit the coach's memory and skills to its private repository" in lines


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["render", "--out", "x"], "--env"),
        (["render", "--env", "x"], "--out"),
        (["preflight", "--admin-uid", "0"], "--env"),
        (["preflight", "--env", "x"], "--admin-uid"),
        (["backup", "--keep", "1"], "--data-dir"),
        (["backup", "--data-dir", "x"], "--keep"),
        (["memory-commit", "--repo", "x"], "--hermes-home"),
        (["memory-commit", "--hermes-home", "x"], "--repo"),
    ],
)
def test_every_option_is_required(
    argv: list[str], missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        main(argv)

    assert exited.value.code == 2
    assert f"the following arguments are required: {missing}" in capsys.readouterr().err


def test_memory_commit_records_what_was_learned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "hermes"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "USER.md").write_text("Trains four days a week.\n")
    argv = ["memory-commit", "--hermes-home", str(home), "--repo", str(tmp_path / "memory.git")]

    assert main(argv) == 0
    assert re.fullmatch(r"committed [0-9a-f]{40}\n", capsys.readouterr().out)

    assert main(argv) == 0
    assert capsys.readouterr().out == "nothing learned; nothing to do\n"


def test_memory_commit_reports_a_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "missing"
    argv = ["memory-commit", "--hermes-home", str(home), "--repo", str(tmp_path / "memory.git")]

    assert main(argv) == 1

    assert capsys.readouterr().err == f"memory-commit: {home} is not a directory\n"


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
