"""The inbox and the browsers notices are pushed to.

Times are UTC ISO strings of one shape (``utc_iso``), so they compare as text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from trainer.domain.notices import Notice, NoticeKind

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True)
class StoredNotice:
    """A notice in the inbox: shown from ``at``, read once ``read``."""

    id: int
    kind: NoticeKind
    title: str
    body: str
    at: str
    read: bool


@dataclass(frozen=True)
class Subscription:
    """Where a browser's push service takes its pushes, and the keys they are for.

    ``p256dh`` and ``auth`` are the browser's base64url keys, as it gave them;
    ``server_key`` is the server's public key it subscribed with.
    """

    endpoint: str
    p256dh: str
    auth: str
    server_key: str


def insert_notice(conn: sqlite3.Connection, notice: Notice, created_at: str, due_at: str) -> int:
    """Add ``notice``, shown (and pushed) from ``due_at``; return its id."""
    row = conn.execute(
        """
        INSERT INTO inbox (kind, title, body, created_at, due_at) VALUES (?, ?, ?, ?, ?)
        RETURNING id
        """,
        (notice.kind, notice.title, notice.body, created_at, due_at),
    ).fetchone()
    return int(row[0])


def _stored(row: sqlite3.Row) -> StoredNotice:
    # By position: rows match column names in any case, so names would hide typos.
    notice_id, kind, title, body, due_at, read_at = row
    return StoredNotice(notice_id, NoticeKind(kind), title, body, due_at, read_at is not None)


def shown_notices(conn: sqlite3.Connection, now: str, limit: int) -> list[StoredNotice]:
    """The newest ``limit`` notices due by ``now``, newest first."""
    rows = conn.execute(
        """
        SELECT id, kind, title, body, due_at, read_at FROM inbox WHERE due_at <= ?
        ORDER BY due_at DESC, id DESC LIMIT ?
        """,
        (now, limit),
    ).fetchall()
    return [_stored(row) for row in rows]


def unread_count(conn: sqlite3.Connection, now: str) -> int:
    """How many notices due by ``now`` are unread."""
    row = conn.execute(
        """SELECT count(*) FROM inbox WHERE due_at <= ? AND read_at IS NULL""", (now,)
    ).fetchone()
    return int(row[0])


def delete_held_notice(conn: sqlite3.Connection, notice_id: int, now: str) -> bool:
    """Delete notice ``notice_id`` if it is not due yet; whether it was."""
    cursor = conn.execute("""DELETE FROM inbox WHERE id = ? AND due_at > ?""", (notice_id, now))
    return cursor.rowcount > 0


def mark_read(conn: sqlite3.Connection, notice_id: int, now: str) -> bool:
    """Mark notice ``notice_id`` read (once); whether it exists."""
    cursor = conn.execute(
        """UPDATE inbox SET read_at = coalesce(read_at, ?) WHERE id = ?""", (now, notice_id)
    )
    return cursor.rowcount > 0


def mark_all_read(conn: sqlite3.Connection, now: str) -> None:
    """Mark every notice due by ``now`` read."""
    conn.execute(
        """UPDATE inbox SET read_at = ? WHERE due_at <= ? AND read_at IS NULL""", (now, now)
    )


def unsent_notices(conn: sqlite3.Connection, now: str) -> list[StoredNotice]:
    """Notices due by ``now`` whose push was not dealt with, oldest first."""
    rows = conn.execute(
        """
        SELECT id, kind, title, body, due_at, read_at FROM inbox
        WHERE due_at <= ? AND sent_at IS NULL ORDER BY due_at, id
        """,
        (now,),
    ).fetchall()
    return [_stored(row) for row in rows]


def claim_unsent(conn: sqlite3.Connection, notice_id: int, now: str) -> bool:
    """Take notice ``notice_id``'s push on; whether it is this caller's to push.

    It is if no one had taken it on yet and it is still unread, both as of
    this statement. A notice read meanwhile is taken on too, and never pushed.
    """
    row = conn.execute(
        """
        UPDATE inbox SET sent_at = ? WHERE id = ? AND sent_at IS NULL
        RETURNING read_at IS NULL
        """,
        (now, notice_id),
    ).fetchone()
    return row is not None and bool(row[0])


def save_subscription(conn: sqlite3.Connection, subscription: Subscription, now: str) -> None:
    """Add a browser's subscription, or replace the keys of one already there."""
    conn.execute(
        """
        INSERT INTO push_subscriptions (endpoint, p256dh, auth, server_key, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth,
            server_key = excluded.server_key
        """,
        (
            subscription.endpoint,
            subscription.p256dh,
            subscription.auth,
            subscription.server_key,
            now,
        ),
    )


def delete_subscription(conn: sqlite3.Connection, endpoint: str) -> bool:
    """Remove the subscription at ``endpoint``; whether there was one."""
    cursor = conn.execute("""DELETE FROM push_subscriptions WHERE endpoint = ?""", (endpoint,))
    return cursor.rowcount > 0


def list_subscriptions(conn: sqlite3.Connection) -> list[Subscription]:
    """Every subscription, oldest first."""
    rows = conn.execute(
        """SELECT endpoint, p256dh, auth, server_key FROM push_subscriptions ORDER BY id"""
    ).fetchall()
    return [Subscription(*row) for row in rows]


def forget_other_subscriptions(conn: sqlite3.Connection, server_key: str) -> int:
    """Remove every subscription not made with ``server_key``; how many there were."""
    cursor = conn.execute(
        """DELETE FROM push_subscriptions WHERE server_key IS NOT ?""", (server_key,)
    )
    return cursor.rowcount
