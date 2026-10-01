"""The Coach tab's endpoints, against a fake gateway."""

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trainer.api.app import create_app
from trainer.api.settings import CoachSettings, Settings
from trainer.services.hermes import GatewayError, GatewayMessage, HermesGateway
from trainer.storage.coach import read_session_id
from trainer.storage.database import connect, migrate

OWNER = "owner@example.com"
AS_OWNER = {"Tailscale-User-Login": OWNER}


class FakeGateway:
    """One in-memory session; ``down`` makes every call fail like an unreachable gateway."""

    def __init__(self) -> None:
        """Up, with nothing said."""
        self.stored: list[GatewayMessage] = []
        self.down = False

    def _check(self) -> None:
        if self.down:
            message = "the coach's gateway is unreachable (refused)"
            raise GatewayError(message)

    def create_session(self, title: str) -> str:
        self._check()
        return f"{title}-1"

    def chat(self, session_id: str, text: str) -> str:
        self._check()
        self.stored += [
            GatewayMessage("user", text, 1_790_000_000.0),
            GatewayMessage("assistant", f"re: {text}", 1_790_000_001.0),
        ]
        return f"re: {text} ({session_id})"

    def messages(self, session_id: str) -> list[GatewayMessage]:  # noqa: ARG002  # why: fake of the Gateway protocol
        self._check()
        return self.stored


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "trainer.db"
    with closing(connect(path)) as conn:
        migrate(conn)
    return path


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(database: Path, gateway: FakeGateway) -> TestClient:
    return TestClient(create_app(Settings(database, OWNER), coach_gateway=gateway))


def test_a_conversation(client: TestClient, database: Path) -> None:
    assert client.get("/api/coach/messages", headers=AS_OWNER).json() == []

    sent = client.post("/api/coach/messages", json={"text": "  hello  "}, headers=AS_OWNER)

    assert sent.status_code == 200
    assert sent.json()["role"] == "assistant"
    assert sent.json()["text"] == "re: hello (Coach-1)"  # stripped, in the durable session
    assert sent.json()["at"].endswith("+00:00")
    with closing(sqlite3.connect(database)) as conn:
        assert read_session_id(conn) == "Coach-1"
    assert client.get("/api/coach/messages", headers=AS_OWNER).json() == [
        {"role": "user", "text": "hello", "at": "2026-09-21T14:13:20+00:00"},
        {"role": "assistant", "text": "re: hello", "at": "2026-09-21T14:13:21+00:00"},
    ]


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_a_message_must_say_something_short(client: TestClient, text: str) -> None:
    response = client.post("/api/coach/messages", json={"text": text}, headers=AS_OWNER)

    assert response.status_code == 422


def test_the_longest_message_is_accepted(client: TestClient) -> None:
    response = client.post("/api/coach/messages", json={"text": "x" * 4000}, headers=AS_OWNER)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/coach/messages"), ("POST", "/api/coach/messages")]
)
def test_the_coach_is_owner_only(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"text": "hi"})

    assert response.status_code == 403


def test_an_unreachable_coach_is_503(
    client: TestClient, gateway: FakeGateway, caplog: pytest.LogCaptureFixture
) -> None:
    client.post("/api/coach/messages", json={"text": "first"}, headers=AS_OWNER)
    gateway.down = True

    with caplog.at_level(logging.WARNING, logger="trainer.api.coach"):
        sent = client.post("/api/coach/messages", json={"text": "hi"}, headers=AS_OWNER)
        read = client.get("/api/coach/messages", headers=AS_OWNER)

    for response in (sent, read):
        assert response.status_code == 503
        assert response.json() == {"detail": "the coach is unavailable; try again soon"}
    assert caplog.messages == ["coach: the coach's gateway is unreachable (refused)"] * 2

    gateway.down = False  # one failed turn does not keep the next one out
    assert (
        client.post("/api/coach/messages", json={"text": "hi"}, headers=AS_OWNER).status_code == 200
    )


def test_one_turn_at_a_time(client: TestClient) -> None:
    turn = client.app.state.coach_turn  # type: ignore[attr-defined]  # why: Starlette types app as ASGIApp
    turn.acquire()
    try:
        response = client.post("/api/coach/messages", json={"text": "hi"}, headers=AS_OWNER)
    finally:
        turn.release()

    assert response.status_code == 409
    assert response.json() == {"detail": "the coach is still answering"}
    assert client.get("/api/coach/messages", headers=AS_OWNER).status_code == 200  # reading is fine


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/coach/messages"), ("POST", "/api/coach/messages")]
)
def test_without_the_coachs_secrets_the_tab_says_so(database: Path, method: str, path: str) -> None:
    client = TestClient(create_app(Settings(database, OWNER)))

    response = client.request(method, path, json={"text": "hi"}, headers=AS_OWNER)

    assert response.status_code == 503
    assert response.json() == {"detail": "the coach is not set up"}


def test_the_gateway_comes_from_the_settings(database: Path) -> None:
    app = create_app(Settings(database, OWNER, coach=CoachSettings("http://127.0.0.1:8642", "k")))

    assert isinstance(app.state.coach_gateway, HermesGateway)
    assert app.state.coach_gateway._base_url == "http://127.0.0.1:8642"  # noqa: SLF001  # why: checking the wiring
    assert app.state.coach_gateway._key == "k"  # noqa: SLF001  # why: checking the wiring
