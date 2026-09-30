"""Nightly database backup and rotation."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from trainer.deploy.backup import backup, prune

NOW = datetime(2026, 9, 30, 3, 30, 5, tzinfo=UTC)


def make_database(data_dir: Path) -> None:
    with closing(sqlite3.connect(data_dir / "trainer.db")) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()


def test_no_database_means_nothing_to_do(tmp_path: Path) -> None:
    assert backup(tmp_path, 3, NOW) is None
    assert not (tmp_path / "backups").exists()


def test_backup_copies_the_database(tmp_path: Path) -> None:
    make_database(tmp_path)

    written = backup(tmp_path, 3, NOW)

    assert written == tmp_path / "backups" / "trainer-20260930T033005Z.db"
    with closing(sqlite3.connect(written)) as conn:
        assert conn.execute("SELECT x FROM t").fetchall() == [(42,)]


def test_backup_reuses_an_existing_backup_directory(tmp_path: Path) -> None:
    make_database(tmp_path)
    (tmp_path / "backups").mkdir()

    assert backup(tmp_path, 3, NOW) is not None


def test_backup_rotates_to_the_newest(tmp_path: Path) -> None:
    make_database(tmp_path)
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in ("20260926", "20260927", "20260928"):
        (backups / f"trainer-{day}T033000Z.db").write_bytes(b"")

    backup(tmp_path, 2, NOW)

    assert sorted(path.name for path in backups.iterdir()) == [
        "trainer-20260928T033000Z.db",
        "trainer-20260930T033005Z.db",
    ]


def test_prune_keeps_unrelated_files_and_reports_deletions(tmp_path: Path) -> None:
    for name in ("trainer-1.db", "trainer-2.db", "trainer-3.db", "notes.txt"):
        (tmp_path / name).write_bytes(b"")

    deleted = prune(tmp_path, 1)

    assert [path.name for path in deleted] == ["trainer-1.db", "trainer-2.db"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["notes.txt", "trainer-3.db"]


def test_prune_with_fewer_backups_than_keep_deletes_nothing(tmp_path: Path) -> None:
    (tmp_path / "trainer-1.db").write_bytes(b"")

    assert prune(tmp_path, 5) == []
    assert (tmp_path / "trainer-1.db").exists()
