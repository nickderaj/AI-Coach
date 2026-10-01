"""The Model Context Protocol over stdio, as far as a tool server needs it.

Messages are JSON-RPC 2.0, one per line. The server answers ``initialize``,
``ping``, ``tools/list`` and ``tools/call``; it ignores notifications and
refuses every other method. That is the whole of what Hermes uses from a tool
server, and the official SDK would add an HTTP stack and a dozen dependencies
to the trainer for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

# Revisions with the initialize handshake, oldest first. The client's is echoed
# when it is one of these; otherwise the newest is offered and the client decides.
PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
SERVER_INFO = {"name": "trainer", "version": "1"}
INSTRUCTIONS = (
    "Read-only access to the owner's training log: workouts, sets, the exercise "
    "catalogue and body weight. Loads are kilograms; dumbbell loads are per hand."
)

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

type Json = dict[str, Any]


class ToolError(Exception):
    """A tool could not answer; the message is shown to the model."""


@dataclass(frozen=True)
class Tool:
    """A tool: what the model sees, and the function that answers it."""

    name: str
    description: str
    input_schema: Json
    call: Callable[[Json], object]


def handle_line(line: str, tools: Mapping[str, Tool]) -> str | None:
    """Answer one line of input; ``None`` when it needs no answer (a notification)."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return _encode(_error(None, PARSE_ERROR, "not JSON"))
    response = handle(message, tools)
    return None if response is None else _encode(response)


def handle(message: object, tools: Mapping[str, Tool]) -> Json | None:
    """Answer one decoded JSON-RPC message."""
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return _error(None, INVALID_REQUEST, "not a JSON-RPC request")
    if "id" not in message:
        return None  # a notification, such as notifications/initialized
    return _dispatch(message["id"], message["method"], message.get("params") or {}, tools)


def _dispatch(request_id: object, name: str, params: object, tools: Mapping[str, Tool]) -> Json:
    if not isinstance(params, dict):
        return _error(request_id, INVALID_PARAMS, "params must be an object")
    method = _METHODS.get(name)
    if method is None:
        return _error(request_id, METHOD_NOT_FOUND, f"unknown method {name}")
    return method(request_id, params, tools)


def _initialize(request_id: object, params: Json, _tools: Mapping[str, Tool]) -> Json:
    requested = params.get("protocolVersion")
    version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1]
    return _result(
        request_id,
        {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        },
    )


def _ping(request_id: object, _params: Json, _tools: Mapping[str, Tool]) -> Json:
    return _result(request_id, {})


def _list(request_id: object, _params: Json, tools: Mapping[str, Tool]) -> Json:
    return _result(request_id, {"tools": [_describe(tool) for tool in tools.values()]})


def _describe(tool: Tool) -> Json:
    return {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}


def _call(request_id: object, params: Json, tools: Mapping[str, Tool]) -> Json:
    name = params.get("name")
    tool = tools.get(name) if isinstance(name, str) else None
    if tool is None:
        return _error(request_id, INVALID_PARAMS, f"unknown tool {name!r}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _error(request_id, INVALID_PARAMS, "arguments must be an object")
    try:
        text = json.dumps(tool.call(arguments), separators=(",", ":"))
    except ToolError as error:
        return _result(request_id, _content(str(error), is_error=True))
    return _result(request_id, _content(text, is_error=False))


def _content(text: str, *, is_error: bool) -> Json:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _result(request_id: object, result: Json) -> Json:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> Json:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _encode(response: Json) -> str:
    return json.dumps(response, separators=(",", ":"))


_METHODS: dict[str, Callable[[object, Json, Mapping[str, Tool]], Json]] = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _list,
    "tools/call": _call,
}
