"""The MCP stdio protocol: JSON-RPC requests in, responses out."""

import json

import pytest

from trainer.mcp.protocol import (
    INSTRUCTIONS,
    PROTOCOL_VERSIONS,
    Json,
    Tool,
    ToolError,
    handle,
    handle_line,
)


def _echo(arguments: Json) -> object:
    if arguments.get("fail"):
        message = "no such thing"
        raise ToolError(message)
    return {"got": arguments, "unicode": "kg ✓"}


TOOLS = {
    "echo": Tool("echo", "Echoes its arguments.", {"type": "object"}, _echo),
    "other": Tool("other", "Another.", {"type": "object", "properties": {}}, lambda _: []),
}


def request(method: str, params: object = None, request_id: object = 1) -> Json:
    message: Json = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def result(response: Json | None, request_id: object = 1) -> Json:
    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == request_id
    assert "error" not in response
    value: Json = response["result"]
    return value


def error(response: Json | None) -> tuple[object, int, str]:
    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert "result" not in response
    return response["id"], response["error"]["code"], response["error"]["message"]


@pytest.mark.parametrize("version", PROTOCOL_VERSIONS)
def test_initialize_agrees_to_any_handshake_version(version: str) -> None:
    response = handle(request("initialize", {"protocolVersion": version}), TOOLS)

    assert result(response) == {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "trainer", "version": "1"},
        "instructions": INSTRUCTIONS,
    }


@pytest.mark.parametrize("params", [{"protocolVersion": "2026-07-28"}, {"protocolVersion": 3}, {}])
def test_initialize_offers_the_newest_handshake_otherwise(params: Json) -> None:
    response = handle(request("initialize", params), TOOLS)

    assert result(response)["protocolVersion"] == "2025-11-25"
    assert PROTOCOL_VERSIONS == ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


def test_the_response_keeps_the_request_id() -> None:
    assert handle(request("ping", request_id="abc"), TOOLS) == {
        "jsonrpc": "2.0",
        "id": "abc",
        "result": {},
    }


def test_tools_are_listed_in_order() -> None:
    assert result(handle(request("tools/list"), TOOLS)) == {
        "tools": [
            {
                "name": "echo",
                "description": "Echoes its arguments.",
                "inputSchema": {"type": "object"},
            },
            {
                "name": "other",
                "description": "Another.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
    }


def test_a_call_returns_the_answer_as_json_text() -> None:
    response = handle(request("tools/call", {"name": "echo", "arguments": {"a": 1}}), TOOLS)

    assert result(response) == {
        "content": [{"type": "text", "text": '{"got":{"a":1},"unicode":"kg \\u2713"}'}],
        "isError": False,
    }


@pytest.mark.parametrize("params", [{"name": "echo"}, {"name": "echo", "arguments": None}])
def test_arguments_default_to_an_empty_object(params: Json) -> None:
    text = result(handle(request("tools/call", params), TOOLS))["content"][0]["text"]

    assert json.loads(text)["got"] == {}


def test_a_tool_error_is_a_result_the_model_can_read() -> None:
    response = handle(request("tools/call", {"name": "echo", "arguments": {"fail": 1}}), TOOLS)

    assert result(response) == {
        "content": [{"type": "text", "text": "no such thing"}],
        "isError": True,
    }


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"name": "nope"}, "unknown tool 'nope'"),
        ({}, "unknown tool None"),
        ({"name": ["echo"]}, "unknown tool ['echo']"),  # unhashable: never looked up
        ({"name": "echo", "arguments": [1]}, "arguments must be an object"),
    ],
)
def test_bad_calls_are_refused(params: Json, message: str) -> None:
    assert error(handle(request("tools/call", params, request_id=7), TOOLS)) == (
        7,
        -32602,
        message,
    )


def test_params_must_be_an_object() -> None:
    assert error(handle(request("ping", [1]), TOOLS)) == (1, -32602, "params must be an object")


def test_unknown_methods_are_refused() -> None:
    assert error(handle(request("resources/list"), TOOLS)) == (
        1,
        -32601,
        "unknown method resources/list",
    )


@pytest.mark.parametrize(
    "message",
    [[1], "ping", {"id": 1}, {"id": 1, "method": 5}, None],
)
def test_malformed_messages_are_invalid_requests(message: object) -> None:
    assert error(handle(message, TOOLS)) == (None, -32600, "not a JSON-RPC request")


def test_notifications_get_no_answer() -> None:
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, TOOLS) is None
    assert handle_line('{"jsonrpc":"2.0","method":"notifications/initialized"}', TOOLS) is None


def test_a_line_is_answered_with_one_compact_line() -> None:
    assert handle_line('{"jsonrpc": "2.0", "id": 2, "method": "ping"}', TOOLS) == (
        '{"jsonrpc":"2.0","id":2,"result":{}}'
    )


def test_a_line_that_is_not_json_is_a_parse_error() -> None:
    assert handle_line("{nope", TOOLS) == (
        '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"not JSON"}}'
    )
