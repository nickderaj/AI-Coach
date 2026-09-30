"""Nightly online backup of the SQLite database, with rotation."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

from trainer.storage.database import DATABASE_FILE

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

BACKUP_DIR = "backups"


def backup(data_dir: Path, keep: int, now: datetime) -> Path | None:
    """Copy the database with SQLite's online backup API, then keep the newest ``keep``.

    Returns:
        The new backup's path, or ``None`` when there is no database yet.
    """
    database = data_dir / DATABASE_FILE
    if not database.exists():
        return None
    target_dir = data_dir / BACKUP_DIR
    target_dir.mkdir(exist_ok=True)
    target = target_dir / f"trainer-{now:%Y%m%dT%H%M%SZ}.db"
    with (
        closing(sqlite3.connect(database)) as source,
        closing(sqlite3.connect(target)) as destination,
    ):
        source.backup(destination)
    prune(target_dir, keep)
    return target


def prune(target_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` backups; return what was deleted."""
    backups = sorted(target_dir.glob("trainer-*.db"))
    stale = backups[:-keep]
    for path in stale:
        path.unlink()
    return stale
