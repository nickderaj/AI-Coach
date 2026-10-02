"""The Coach tab's endpoints: one durable conversation with the coach."""

from __future__ import annotations

import logging
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from trainer.services.coach import CoachMessage, Gateway, history, take_turn
from trainer.services.hermes import GatewayError
from trainer.storage.database import connect

if TYPE_CHECKING:
    from threading import Lock

router = APIRouter(prefix="/api/coach")
logger = logging.getLogger(__name__)

# The longest message the tab sends; a coach question, not a document.
MAX_MESSAGE_LENGTH = 4000


class MessageIn(BaseModel):
    """What the owner says to the coach."""

    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH)
    ]


def _gateway(request: Request) -> Gateway:
    gateway: Gateway | None = request.app.state.coach_gateway
    if gateway is None:
        raise HTTPException(status_code=503, detail="the coach is not set up")
    return gateway


def _unavailable(error: GatewayError) -> HTTPException:
    logger.warning("coach: %s", error)
    return HTTPException(status_code=503, detail="the coach is unavailable; try again soon")


@router.get("/messages")
def messages(request: Request) -> list[CoachMessage]:
    """The conversation so far, oldest first."""
    gateway = _gateway(request)
    try:
        with closing(connect(request.app.state.settings.database)) as conn:
            return history(conn, gateway)
    except GatewayError as error:
        raise _unavailable(error) from error


class ReplyOut(BaseModel):
    """The coach's reply, and the notice of it the app claims if it shows the reply."""

    role: Literal["assistant"]
    text: str
    at: str
    notice_id: int


@router.post("/messages")
def post_message(request: Request, body: MessageIn) -> ReplyOut:
    """Say something to the coach and wait for its reply; one turn at a time.

    The reply comes with a held notice: ``POST /api/inbox/{notice_id}/seen``
    while the reply is on screen, or the owner is told of it.
    """
    gateway = _gateway(request)
    turn: Lock = request.app.state.coach_turn
    if not turn.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="the coach is still answering")
    try:
        with closing(connect(request.app.state.settings.database)) as conn:
            done = take_turn(conn, gateway, body.text, lambda: datetime.now(UTC))
    except GatewayError as error:
        raise _unavailable(error) from error
    finally:
        turn.release()
    return ReplyOut(
        role="assistant", text=done.reply.text, at=done.reply.at, notice_id=done.notice_id
    )
