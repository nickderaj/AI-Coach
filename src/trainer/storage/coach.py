"""The coach's conversation: which Hermes session the Coach tab continues."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


def read_session_id(conn: sqlite3.Connection) -> str | None:
    """The Hermes session the Coach tab continues, if one was started."""
    row = conn.execute("""SELECT session_id FROM coach WHERE id = 1""").fetchone()
    return None if row is None else str(row[0])


def save_session_id(conn: sqlite3.Connection, session_id: str) -> None:
    """Make ``session_id`` the conversation the Coach tab continues."""
    conn.execute(
        """
        INSERT INTO coach (id, session_id) VALUES (1, ?)
        ON CONFLICT (id) DO UPDATE SET session_id = excluded.session_id
        """,
        (session_id,),
    )
