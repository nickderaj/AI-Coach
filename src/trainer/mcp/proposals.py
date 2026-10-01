"""Proposing a program: the one thing the coach writes, and it does so through the API.

The tool server runs in the coach's sandbox, where the training log is
read-only. A proposal is sent to the API on loopback, which checks it and saves
it through services, authenticated with the gateway's key. The owner accepts it
in the app; the coach never changes the active program (D12).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from trainer.mcp.protocol import ToolError

if TYPE_CHECKING:
    from trainer.services.programs import ProgramIn

# Saving a program is one quick write; the coach's tool call times out at 30 s.
TIMEOUT_S = 20.0
PROPOSAL_PATH = "/api/programs/proposal"
JSON = "application/json"


class ProgramsApi:
    """The API's proposal endpoint, on loopback, authenticated with the gateway's key."""

    def __init__(
        self,
        base_url: str,
        key: str,
        *,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        """Send proposals to the API at ``base_url`` (``http://host:port``) with ``key``."""
        self._base_url = base_url
        self._key = key
        # No proxies, whatever the environment says: the key goes to the API alone.
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def propose(self, program: ProgramIn) -> object:
        """Save ``program`` as the proposal; return it as the API saved it.

        Raises:
            ToolError: with the API's reason if it refused the program, or if it
                could not be reached.
        """
        # pragma: no mutate start  # why: urllib capitalises header names; case mutants are equal
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": JSON, "Accept": JSON}
        # pragma: no mutate end  # why: closes the block above
        request = urllib.request.Request(  # noqa: S310  # why: the URL is the configured loopback API
            self._base_url + PROPOSAL_PATH,
            data=program.model_dump_json().encode(),
            headers=headers,
            method="PUT",
        )
        try:
            with self._opener.open(request, timeout=TIMEOUT_S) as response:
                saved: object = json.load(response)
        except urllib.error.HTTPError as error:
            raise ToolError(_refusal(error)) from error
        except (OSError, json.JSONDecodeError) as error:
            message = f"the app cannot be reached to save the program ({error})"
            raise ToolError(message) from error
        return saved


def _refusal(error: urllib.error.HTTPError) -> str:
    """The API's reason, when it gave one as text (an exercise that cannot be used)."""
    try:
        body: Any = json.load(error)
        detail = body["detail"]
    except (OSError, ValueError, TypeError, KeyError):
        detail = None
    if isinstance(detail, str):
        return f"the program was not saved: {detail}"
    return f"the program was not saved: the app answered {error.code}"
