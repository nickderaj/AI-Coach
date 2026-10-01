"""The Coach tab's conversation: one durable session, started on first use."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import override

import pytest

from trainer.services.coach import (
    HISTORY_LIMIT,
    SESSION_TITLE,
    CoachMessage,
    history,
    send,
)
from trainer.services.hermes import GatewayError, GatewayMessage, SessionNotFoundError
from trainer.storage.coach import read_session_id, save_session_id

NOW = datetime(2026, 10, 1, 13, 0, 5, tzinfo=UTC)


class FakeGateway:
    """Sessions held in memory; a turn answers "re: <text>"."""

    def __init__(self) -> None:
        """No sessions yet."""
        self.sessions: dict[str, list[GatewayMessage]] = {}
        self.titles: list[str] = []
        self.chats: list[tuple[str, str]] = []

    def create_session(self, title: str) -> str:
        self.titles.append(title)
        session_id = f"s{len(self.titles)}"
        self.sessions[session_id] = []
        return session_id

    def chat(self, session_id: str, text: str) -> str:
        self.chats.append((session_id, text))
        if session_id not in self.sessions:
            raise SessionNotFoundError(session_id)
        reply = f"re: {text}"
        stamp = float(len(self.sessions[session_id]))
        self.sessions[session_id] += [
            GatewayMessage("user", text, stamp),
            GatewayMessage("assistant", reply, stamp + 0.5),
        ]
        return reply

    def messages(self, session_id: str) -> list[GatewayMessage]:
        if session_id not in self.sessions:
            raise SessionNotFoundError(session_id)
        return self.sessions[session_id]


def test_the_first_message_starts_the_durable_session(db: sqlite3.Connection) -> None:
    gateway = FakeGateway()

    reply = send(db, gateway, "hello", lambda: NOW)

    assert reply == CoachMessage("assistant", "re: hello", "2026-10-01T13:00:05+00:00")
    assert gateway.titles == [SESSION_TITLE] == ["Coach"]
    assert read_session_id(db) == "s1"
    assert not db.in_transaction  # saved for good before the turn


def test_later_messages_continue_it(db: sqlite3.Connection) -> None:
    gateway = FakeGateway()
    send(db, gateway, "one", lambda: NOW)

    send(db, gateway, "two", lambda: NOW)

    assert gateway.titles == ["Coach"]
    assert gateway.chats == [("s1", "one"), ("s1", "two")]


def test_a_session_hermes_lost_is_started_again(db: sqlite3.Connection) -> None:
    gateway = FakeGateway()
    save_session_id(db, "gone")

    reply = send(db, gateway, "still there?", lambda: NOW)

    assert reply.text == "re: still there?"
    assert gateway.chats == [("gone", "still there?"), ("s1", "still there?")]
    assert read_session_id(db) == "s1"


@pytest.mark.usefixtures("far_east_timezone")
def test_the_reply_time_is_utc(db: sqlite3.Connection) -> None:
    local = NOW.astimezone(timezone(timedelta(hours=1)))

    assert send(db, FakeGateway(), "x", lambda: local).at == "2026-10-01T13:00:05+00:00"


def test_the_reply_is_stamped_when_it_arrives(db: sqlite3.Connection) -> None:
    events: list[str] = []

    class Recording(FakeGateway):
        @override
        def chat(self, session_id: str, text: str) -> str:
            events.append("turn")
            return super().chat(session_id, text)

    def clock() -> datetime:
        events.append("clock")
        return NOW

    send(db, Recording(), "x", clock)

    assert events == ["turn", "clock"]


def test_gateway_errors_reach_the_caller(db: sqlite3.Connection) -> None:
    class Down(FakeGateway):
        @override
        def chat(self, session_id: str, text: str) -> str:
            message = "unreachable"
            raise GatewayError(message)

    with pytest.raises(GatewayError, match="unreachable"):
        send(db, Down(), "x", lambda: NOW)


def test_no_history_before_the_first_message(db: sqlite3.Connection) -> None:
    gateway = FakeGateway()

    assert history(db, gateway) == []
    assert gateway.titles == []  # reading never starts a session


@pytest.mark.usefixtures("far_east_timezone")
def test_history_shows_what_was_said_oldest_first(db: sqlite3.Connection) -> None:
    gateway = FakeGateway()
    gateway.sessions["s"] = [
        GatewayMessage("user", "what did I bench?", 1_790_859_428.6),
        GatewayMessage("assistant", "", 1_790_859_430.9, calls_tools=True),  # a tool call
        # Commentary written alongside tool calls: a step of the turn, not its answer.
        GatewayMessage("assistant", "Let me look that up.", 1_790_859_430.95, calls_tools=True),
        GatewayMessage("tool", '{"sets": []}', 1_790_859_431.0),
        GatewayMessage("assistant", "  \n", 1_790_859_431.5),
        GatewayMessage("system", "be brief", 1_790_859_431.7),
        GatewayMessage("assistant", "60 kg x 8", 1_790_859_433.5),
    ]
    save_session_id(db, "s")

    assert history(db, gateway) == [
        CoachMessage("user", "what did I bench?", "2026-10-01T12:57:08+00:00"),
        CoachMessage("assistant", "60 kg x 8", "2026-10-01T12:57:13+00:00"),
    ]


def test_history_keeps_the_newest_messages(db: sqlite3.Connection) -> None:
    gateway = FakeGateway()
    for turn in range(HISTORY_LIMIT):
        send(db, gateway, f"m{turn}", lambda: NOW)

    shown = history(db, gateway)

    assert HISTORY_LIMIT == 100
    assert len(shown) == HISTORY_LIMIT
    assert shown[0].text == f"m{HISTORY_LIMIT // 2}"
    assert shown[-1].text == f"re: m{HISTORY_LIMIT - 1}"


def test_a_lost_session_has_no_history(db: sqlite3.Connection) -> None:
    save_session_id(db, "gone")

    assert history(db, FakeGateway()) == []
