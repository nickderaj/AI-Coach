"""The Hermes gateway client, against a fake gateway (no sockets)."""

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message

import pytest

from trainer.services.hermes import (
    PAGE_LIMIT,
    TURN_TIMEOUT_S,
    GatewayError,
    GatewayMessage,
    HermesGateway,
    SessionNotFoundError,
)

type Answer = tuple[int, object] | Exception
type Route = Callable[[urllib.request.Request], Answer]


class FakeResponse(urllib.response.addinfourl):
    """A response as urllib's handlers expect one (they read ``msg``)."""

    msg = "fake"


class FakeGateway(urllib.request.BaseHandler):
    """Answers http:// requests from a table of routes; records each request."""

    handler_order = 10  # before urllib's own proxy and HTTP handlers

    def __init__(self, routes: dict[str, Answer | Route]) -> None:
        """Answer from ``routes``, keyed "METHOD /path?query"."""
        self.routes = routes
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float | None] = []

    def http_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        self.requests.append(request)
        self.timeouts.append(request.timeout)
        key = f"{request.get_method()} {request.selector}"
        answer = self.routes[key]
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return FakeResponse(io.BytesIO(raw), Message(), request.full_url, status)


def gateway(routes: dict[str, Answer | Route]) -> tuple[HermesGateway, FakeGateway]:
    fake = FakeGateway(routes)
    opener = urllib.request.build_opener(fake)
    return HermesGateway("http://127.0.0.1:8642", "secret", opener=opener), fake


def body(request: urllib.request.Request) -> object:
    assert isinstance(request.data, bytes)
    return json.loads(request.data)


def test_create_session() -> None:
    client, fake = gateway({"POST /api/sessions": (200, {"session": {"id": "api_1", "x": 1}})})

    assert client.create_session("Coach") == "api_1"

    (request,) = fake.requests
    assert request.full_url == "http://127.0.0.1:8642/api/sessions"
    assert request.get_method() == "POST"
    assert body(request) == {"title": "Coach"}
    assert request.get_header("Authorization") == "Bearer secret"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Accept") == "application/json"
    assert fake.timeouts == [TURN_TIMEOUT_S]
    assert TURN_TIMEOUT_S == 240.0


def test_chat_returns_the_reply() -> None:
    client, fake = gateway(
        {
            "POST /api/sessions/api%2F1/chat": (
                200,
                {"message": {"role": "assistant", "content": "Hi"}},
            )
        }
    )

    assert client.chat("api/1", "hello") == "Hi"  # the id is one path segment

    assert body(fake.requests[0]) == {"input": "hello"}


def test_messages_are_the_newest_page_oldest_first() -> None:
    page = {
        "data": [
            {"role": "assistant", "content": "Hi", "timestamp": 2.5, "id": "2"},
            {"role": "user", "content": "hello", "timestamp": 1.0, "id": "1"},
            {"role": "assistant", "content": None, "timestamp": 2.0, "id": "3"},
        ]
    }
    client, fake = gateway(
        {f"GET /api/sessions/api_1/messages?order=latest&limit={PAGE_LIMIT}": (200, page)}
    )

    assert client.messages("api_1") == [
        GatewayMessage("user", "hello", 1.0),
        GatewayMessage("assistant", "", 2.0),
        GatewayMessage("assistant", "Hi", 2.5),
    ]
    assert fake.requests[0].data is None
    assert fake.requests[0].get_method() == "GET"
    assert PAGE_LIMIT == 500


def http_error(status: int, payload: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", status, "no", Message(), io.BytesIO(payload))


def test_a_missing_session_is_its_own_error() -> None:
    missing = b'{"error": {"message": "Session not found: x", "code": "session_not_found"}}'
    client, _ = gateway({"POST /api/sessions/x/chat": http_error(404, missing)})

    with pytest.raises(
        SessionNotFoundError, match=r"^the coach's session is gone \(session_not_found\)$"
    ):
        client.chat("x", "hello")


@pytest.mark.parametrize(
    ("status", "payload", "message"),
    [
        (404, b'{"error": {"code": "not_found"}}', "404 not_found"),
        (401, b'{"error": {"code": "invalid_api_key"}}', "401 invalid_api_key"),
        (429, b"busy", "429 unknown"),
        (500, b'{"error": "x"}', "500 unknown"),
        (500, b"[]", "500 unknown"),
    ],
)
def test_other_refusals(status: int, payload: bytes, message: str) -> None:
    client, _ = gateway({"POST /api/sessions": http_error(status, payload)})

    with pytest.raises(GatewayError) as caught:
        client.create_session("Coach")

    assert not isinstance(caught.value, SessionNotFoundError)
    assert str(caught.value) == f"the coach's gateway refused the request ({message})"


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError("refused"), TimeoutError("timed out"), ConnectionResetError("reset")],
)
def test_an_unreachable_gateway(failure: Exception) -> None:
    client, _ = gateway({"POST /api/sessions": failure})

    with pytest.raises(GatewayError, match=r"^the coach's gateway is unreachable \(.+\)$"):
        client.create_session("Coach")


def test_an_answer_that_is_not_json() -> None:
    client, _ = gateway({"POST /api/sessions": (200, b"<html>")})

    with pytest.raises(
        GatewayError, match=r"^the coach's gateway is unreachable \(Expecting value"
    ):
        client.create_session("Coach")


@pytest.mark.parametrize(
    ("call", "answer"),
    [
        ("create", {"session": {}}),
        ("chat", {"message": {"content": None}}),
        ("messages", {"data": [{"role": "user"}]}),
        ("messages", []),
    ],
)
def test_an_answer_of_the_wrong_shape(call: str, answer: object) -> None:
    client, _ = gateway(
        {
            "POST /api/sessions": (200, answer),
            "POST /api/sessions/s/chat": (200, answer),
            f"GET /api/sessions/s/messages?order=latest&limit={PAGE_LIMIT}": (200, answer),
        }
    )
    calls: dict[str, Callable[[], object]] = {
        "create": lambda: client.create_session("Coach"),
        "chat": lambda: client.chat("s", "x"),
        "messages": lambda: client.messages("s"),
    }

    with pytest.raises(
        GatewayError,
        match=r"^the coach's gateway answered in an unexpected shape \(\d+ problems?\)$",
    ):
        calls[call]()


def test_the_default_opener_uses_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://proxy.example.com:3128")
    fake = FakeGateway({"POST /api/sessions": (200, {"session": {"id": "a"}})})
    build = urllib.request.build_opener
    given: list[urllib.request.BaseHandler] = []

    def build_with_fake(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
        given.extend(handlers)
        return build(fake, *handlers)

    monkeypatch.setattr(urllib.request, "build_opener", build_with_fake)

    assert HermesGateway("http://127.0.0.1:1", "k").create_session("Coach") == "a"
    (proxies,) = given
    assert isinstance(proxies, urllib.request.ProxyHandler)
    assert proxies.proxies == {}  # type: ignore[attr-defined]  # why: set by ProxyHandler.__init__
    assert fake.timeouts == [240.0]
