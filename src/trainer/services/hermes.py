"""A client for the coach's Hermes gateway: its authenticated Sessions API on loopback."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from typing import Any

# A turn can call several tools and the model more than once; the phone waits.
TURN_TIMEOUT_S = 240.0
# Hermes's largest page of messages; tool calls and results count towards it.
PAGE_LIMIT = 500
JSON = "application/json"


class GatewayError(RuntimeError):
    """The gateway could not be reached, or did not answer as expected."""


class SessionNotFoundError(GatewayError):
    """The gateway has no session with that id."""


@dataclass(frozen=True)
class GatewayMessage:
    """One stored message of a session: user, assistant or tool."""

    role: str
    content: str
    timestamp: float
    # An assistant message that called tools: a step of a turn, not its answer.
    # Its content, if any, is commentary written alongside the calls.
    calls_tools: bool = False


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Session(_Lenient):
    id: str


class _Created(_Lenient):
    session: _Session


class _Reply(_Lenient):
    content: str


class _Answered(_Lenient):
    message: _Reply


class _Stored(_Lenient):
    role: str
    content: str | None
    timestamp: float
    tool_calls: list[object] | None = None


class _Page(_Lenient):
    data: list[_Stored]


class HermesGateway:
    """The Sessions API of one Hermes gateway, authenticated with its API key."""

    def __init__(
        self,
        base_url: str,
        key: str,
        *,
        opener: urllib.request.OpenerDirector | None = None,
        timeout: float = TURN_TIMEOUT_S,
    ) -> None:
        """Talk to the gateway at ``base_url`` (``http://host:port``, no slash) with ``key``."""
        self._base_url = base_url
        self._key = key
        # No proxies, whatever the environment says: the key goes to the gateway alone.
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._timeout = timeout

    def create_session(self, title: str) -> str:
        """Start an empty session; return its id."""
        answer = self._request("/api/sessions", {"title": title})
        return _parse(_Created, answer).session.id

    def chat(self, session_id: str, text: str) -> str:
        """Run one turn of ``session_id`` with ``text``; return the assistant's reply."""
        answer = self._request(f"/api/sessions/{_segment(session_id)}/chat", {"input": text})
        return _parse(_Answered, answer).message.content

    def messages(self, session_id: str) -> list[GatewayMessage]:
        """The newest stored messages of ``session_id``, oldest first.

        Hermes pages by insertion order and returns the page oldest first; it is
        kept as it is. Timestamps are not an order: clocks can be set back.
        """
        path = f"/api/sessions/{_segment(session_id)}/messages?order=latest&limit={PAGE_LIMIT}"
        stored = _parse(_Page, self._request(path)).data
        return [
            GatewayMessage(item.role, item.content or "", item.timestamp, bool(item.tool_calls))
            for item in stored
        ]

    def _request(self, path: str, body: object = None) -> object:
        """GET ``path``, or POST ``body`` as JSON to it; return the JSON answer."""
        data = None if body is None else json.dumps(body).encode()
        # pragma: no mutate start  # why: urllib capitalises header names; case mutants are equal
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": JSON, "Accept": JSON}
        # pragma: no mutate end  # why: closes the block above
        request = urllib.request.Request(  # noqa: S310  # why: the URL is the configured loopback gateway
            self._base_url + path, data=data, headers=headers
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                payload: object = json.load(response)
        except urllib.error.HTTPError as error:
            raise _refusal(error) from error
        except (OSError, json.JSONDecodeError) as error:
            message = f"the coach's gateway is unreachable ({error})"
            raise GatewayError(message) from error
        return payload


def _segment(session_id: str) -> str:
    # Nothing is safe, not even "/": the id must stay one path segment.
    return quote(session_id, safe="")  # pragma: no mutate  # why: letters in safe change nothing


def _parse[Model: BaseModel](model: type[Model], payload: object) -> Model:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        message = (
            f"the coach's gateway answered in an unexpected shape ({error.error_count()} problems)"
        )
        raise GatewayError(message) from error


def _refusal(error: urllib.error.HTTPError) -> GatewayError:
    code = _error_code(error)
    if error.code == HTTPStatus.NOT_FOUND and code == "session_not_found":
        return SessionNotFoundError(f"the coach's session is gone ({code})")
    return GatewayError(f"the coach's gateway refused the request ({error.code} {code})")


def _error_code(error: urllib.error.HTTPError) -> str:
    try:
        body: Any = json.load(error)
        return str(body["error"]["code"])
    except (OSError, ValueError, TypeError, KeyError):
        return "unknown"
