"""The Coach tab: one durable conversation with the coach (a Hermes session)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from trainer.services.hermes import SessionNotFoundError
from trainer.storage.coach import read_session_id, save_session_id

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from trainer.services.hermes import GatewayMessage

SESSION_TITLE = "Coach"
# The most messages the tab shows; older ones stay in the coach's session search.
HISTORY_LIMIT = 100


class Gateway(Protocol):
    """What the coach needs from Hermes (``trainer.services.hermes.HermesGateway``)."""

    def create_session(self, title: str) -> str:
        """Start an empty session; return its id."""
        ...

    def chat(self, session_id: str, text: str) -> str:
        """Run one turn; return the reply."""
        ...

    def messages(self, session_id: str) -> list[GatewayMessage]:
        """The newest stored messages, oldest first."""
        ...


@dataclass(frozen=True)
class CoachMessage:
    """One message of the conversation as the tab shows it."""

    role: Literal["user", "assistant"]
    text: str
    at: str  # ISO 8601, UTC


def send(
    conn: sqlite3.Connection, gateway: Gateway, text: str, clock: Callable[[], datetime]
) -> CoachMessage:
    """Tell the coach ``text`` in the durable session; return its reply.

    The reply is stamped with ``clock()`` when it arrives, after the turn.

    The session is started on first use, and started again if Hermes no longer
    has it (its memory and skills carry over; only the transcript is new).

    Raises:
        GatewayError: if the gateway cannot be reached or refuses.
    """
    session_id = read_session_id(conn) or _start(conn, gateway)
    try:
        reply = gateway.chat(session_id, text)
    except SessionNotFoundError:
        reply = gateway.chat(_start(conn, gateway), text)
    return CoachMessage("assistant", reply, clock().astimezone(UTC).isoformat(timespec="seconds"))


def history(conn: sqlite3.Connection, gateway: Gateway) -> list[CoachMessage]:
    """The conversation so far, oldest first: what was said, without tool traffic.

    Raises:
        GatewayError: if the gateway cannot be reached or refuses.
    """
    session_id = read_session_id(conn)
    if session_id is None:
        return []
    try:
        stored = gateway.messages(session_id)
    except SessionNotFoundError:
        return []  # the next message starts a new session
    shown = [
        CoachMessage(
            "user" if message.role == "user" else "assistant",
            message.content,
            datetime.fromtimestamp(message.timestamp, UTC).isoformat(timespec="seconds"),
        )
        for message in stored
        if message.role in {"user", "assistant"} and message.content.strip()
    ]
    return shown[-HISTORY_LIMIT:]


def _start(conn: sqlite3.Connection, gateway: Gateway) -> str:
    session_id = gateway.create_session(SESSION_TITLE)
    save_session_id(conn, session_id)
    conn.commit()
    return session_id
