"""``propose_program``: the coach's one write, through the API (no sockets)."""

import io
import json
import sqlite3
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trainer.api.app import create_app
from trainer.api.settings import CoachSettings, Settings
from trainer.mcp.__main__ import programs_api, serve
from trainer.mcp.proposals import TIMEOUT_S, ProgramsApi
from trainer.mcp.protocol import ToolError
from trainer.mcp.tools import PROPOSE_DESCRIPTION, inline_refs, tools
from trainer.services.programs import ProgramIn

OWNER = {"Tailscale-User-Login": "owner@example.com"}
KEY = "gateway-key"
URL = "http://127.0.0.1:8000"


class FakeResponse(urllib.response.addinfourl):
    """A response as urllib's handlers expect one (they read ``msg``)."""

    msg = "fake"


class ApiBridge(urllib.request.BaseHandler):
    """Hands each http:// request to the app in-process; records them."""

    handler_order = 10  # before urllib's own proxy and HTTP handlers

    def __init__(self, client: TestClient) -> None:
        """Answer requests with ``client``'s app."""
        self.client = client
        self.requests: list[urllib.request.Request] = []

    def http_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        self.requests.append(request)
        response = self.client.request(
            request.get_method(),
            request.selector,
            content=request.data if isinstance(request.data, bytes) else None,
            headers=dict(request.header_items()),
        )
        return FakeResponse(
            io.BytesIO(response.content), Message(), request.full_url, response.status_code
        )


class Raising(urllib.request.BaseHandler):
    """Fails every http:// request with ``error``, or answers with ``body``."""

    handler_order = 10

    def __init__(self, error: Exception | None = None, body: bytes = b"") -> None:
        """Raise ``error`` if given, else answer 200 with ``body``."""
        self.error = error
        self.body = body
        self.timeouts: list[float | None] = []

    def http_open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        self.timeouts.append(request.timeout)
        if self.error is not None:
            raise self.error
        return FakeResponse(io.BytesIO(self.body), Message(), request.full_url, 200)


@pytest.fixture
def app(imported: sqlite3.Connection, tmp_path: Path) -> TestClient:
    """The API over the fixture log, with the coach's key configured."""
    imported.commit()
    settings = Settings(
        database=tmp_path / "trainer.db",
        owner_login="owner@example.com",
        coach=CoachSettings("http://127.0.0.1:1", KEY),
    )
    return TestClient(create_app(settings))


def ids(app: TestClient) -> dict[str, int]:
    return {e["name"]: e["id"] for e in app.get("/api/exercises", headers=OWNER).json()}


def program(exercise_id: int, **change: object) -> dict[str, Any]:
    exercise = {"exercise_id": exercise_id, "sets": 3, "rep_min": 8, "rep_max": 10} | change
    return {"name": "Push", "days": [{"name": "A", "blocks": [{"exercises": [exercise]}]}]}


def propose_tool(app: TestClient, key: str = KEY) -> tuple[Any, ApiBridge]:
    bridge = ApiBridge(app)
    api = ProgramsApi(URL, key, opener=urllib.request.build_opener(bridge))
    return tools(Path(), api)["propose_program"].call, bridge


def test_a_proposal_is_saved_through_the_api(app: TestClient) -> None:
    bench = ids(app)["Barbell Bench Press"]
    call, bridge = propose_tool(app)

    answer = call(program(bench, start_load_kg=60))

    assert isinstance(answer, dict)
    assert answer["next"] == (
        "The owner reviews it in the app's Program screen and accepts it there."
    )
    proposed = answer["proposed"]
    assert (proposed["name"], proposed["status"]) == ("Push", "proposed")
    assert proposed["days"][0]["blocks"][0]["exercises"][0]["start_load_kg"] == 60.0
    assert app.get("/api/programs", headers=OWNER).json()["proposed"] == proposed
    (request,) = bridge.requests
    assert (request.get_method(), request.full_url) == ("PUT", f"{URL}/api/programs/proposal")
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Accept") == "application/json"
    assert request.timeout == TIMEOUT_S == 20.0
    assert isinstance(request.data, bytes)
    assert json.loads(request.data) == ProgramIn.model_validate(
        program(bench, start_load_kg=60)
    ).model_dump(mode="json")


def test_the_apis_reason_reaches_the_coach(app: TestClient) -> None:
    call, _ = propose_tool(app)

    with pytest.raises(ToolError, match=r"^the program was not saved: no exercise has id 999$"):
        call(program(999))


def test_a_wrong_key_is_refused(app: TestClient) -> None:
    call, _ = propose_tool(app, key="guess")

    with pytest.raises(ToolError, match=r"^the program was not saved: forbidden$"):
        call(program(ids(app)["Barbell Bench Press"]))

    assert app.get("/api/programs", headers=OWNER).json()["proposed"] is None


def test_bad_arguments_never_reach_the_api(app: TestClient) -> None:
    call, bridge = propose_tool(app)

    with pytest.raises(ToolError) as raised:
        call(program(1, rep_min=12))

    assert str(raised.value) == (
        "invalid arguments: days.0.blocks.0.exercises.0: Value error, rep_max is below rep_min"
    )
    assert bridge.requests == []


@pytest.mark.parametrize(
    ("status", "payload", "message"),
    [
        (422, b'{"detail": "nope"}', "the program was not saved: nope"),
        (422, b'{"detail": [{"loc": []}]}', "the program was not saved: the app answered 422"),
        (500, b"oops", "the program was not saved: the app answered 500"),
        (500, b"[]", "the program was not saved: the app answered 500"),
        (500, b"{}", "the program was not saved: the app answered 500"),
    ],
)
def test_refusals_are_told_to_the_coach(status: int, payload: bytes, message: str) -> None:
    # Built here: an HTTPError's body can be read only once.
    error = urllib.error.HTTPError(URL, status, "no", Message(), io.BytesIO(payload))
    api = ProgramsApi(URL, KEY, opener=urllib.request.build_opener(Raising(error)))

    with pytest.raises(ToolError) as raised:
        api.propose(ProgramIn.model_validate(program(1)))

    assert str(raised.value) == message


def test_an_unreachable_app_is_told_to_the_coach() -> None:
    refused = Raising(urllib.error.URLError("refused"))
    api = ProgramsApi(URL, KEY, opener=urllib.request.build_opener(refused))

    with pytest.raises(ToolError) as raised:
        api.propose(ProgramIn.model_validate(program(1)))

    assert str(raised.value) == (
        "the app cannot be reached to save the program (<urlopen error refused>)"
    )


def test_an_answer_that_is_not_json() -> None:
    api = ProgramsApi(URL, KEY, opener=urllib.request.build_opener(Raising(body=b"<html>")))

    with pytest.raises(ToolError, match=r"^the app cannot be reached to save the program \("):
        api.propose(ProgramIn.model_validate(program(1)))


def test_the_default_opener_uses_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://proxy.example.com:3128")
    fake = Raising(body=b'{"id": 1}')
    build = urllib.request.build_opener
    given: list[urllib.request.BaseHandler] = []

    def build_with_fake(*handlers: urllib.request.BaseHandler) -> urllib.request.OpenerDirector:
        given.extend(handlers)
        return build(fake, *handlers)

    monkeypatch.setattr(urllib.request, "build_opener", build_with_fake)

    assert ProgramsApi(URL, KEY).propose(ProgramIn.model_validate(program(1))) == {"id": 1}
    (proxies,) = given
    assert isinstance(proxies, urllib.request.ProxyHandler)
    assert proxies.proxies == {}  # type: ignore[attr-defined]  # why: set by ProxyHandler.__init__
    assert fake.timeouts == [20.0]


class TestTheTool:
    def test_offered_only_with_a_way_to_save(self) -> None:
        assert "propose_program" not in tools(Path())
        offered = tools(Path(), ProgramsApi(URL, KEY))

        assert list(offered)[-1] == "propose_program"
        tool = offered["propose_program"]
        assert (tool.name, tool.description) == ("propose_program", PROPOSE_DESCRIPTION)
        assert tool.description.endswith(".")

    def test_its_schema_is_plain_nested_json_schema(self) -> None:
        schema = tools(Path(), ProgramsApi(URL, KEY))["propose_program"].input_schema
        text = json.dumps(schema)

        assert "$ref" not in text
        assert "$defs" not in text
        assert schema["additionalProperties"] is False
        assert schema["required"] == ["name", "days"]
        day = schema["properties"]["days"]["items"]
        block = day["properties"]["blocks"]["items"]
        exercise = block["properties"]["exercises"]["items"]
        assert exercise["additionalProperties"] is False
        assert exercise["properties"]["exercise_id"]["minimum"] == 1
        assert block["properties"]["exercises"]["maxItems"] == 3


def test_inline_refs_needs_definitions() -> None:
    with pytest.raises(KeyError):
        inline_refs({"type": "object"})


def test_inline_refs() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"$ref": "#/$defs/A"},
            "list": {"type": "array", "items": [{"$ref": "#/$defs/B"}, 3]},
        },
        "$defs": {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/$defs/B"}}},
            "B": {"type": "integer"},
        },
    }

    assert inline_refs(schema) == {
        "type": "object",
        "properties": {
            "a": {"type": "object", "properties": {"b": {"type": "integer"}}},
            "list": {"type": "array", "items": [{"type": "integer"}, 3]},
        },
    }


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TRAINER_API_URL": URL},
        {"TRAINER_COACH_KEY": KEY},
        {"TRAINER_API_URL": "", "TRAINER_COACH_KEY": KEY},
        {"TRAINER_API_URL": URL, "TRAINER_COACH_KEY": ""},
    ],
)
def test_proposing_needs_the_api_and_the_key(env: dict[str, str]) -> None:
    assert programs_api(env) is None


def test_the_server_offers_proposing_when_set_up(app: TestClient) -> None:
    bridge = ApiBridge(app)
    api = programs_api({"TRAINER_API_URL": URL, "TRAINER_COACH_KEY": KEY})
    assert api is not None
    api._opener = urllib.request.build_opener(bridge)  # noqa: SLF001  # why: no sockets in tests
    out = io.StringIO()
    listing = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    call = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "propose_program",
                "arguments": program(ids(app)["Barbell Bench Press"]),
            },
        }
    )

    serve([listing, call], out, Path(), api)

    listed, called = (json.loads(line) for line in out.getvalue().splitlines())
    assert [tool["name"] for tool in listed["result"]["tools"]][-1] == "propose_program"
    assert called["result"]["isError"] is False
    assert bridge.requests[0].get_header("Authorization") == f"Bearer {KEY}"
