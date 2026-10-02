"""Notifications: browsers subscribing to pushes, and the inbox every notice goes to."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel

from trainer.domain.notices import ROUTES, TEST_NOTICE, NoticeKind
from trainer.services.notices import (
    MAX_ENDPOINT_LENGTH,
    NoticeNotFoundError,
    OtherServerKeyError,
    SubscriptionIn,
    inbox,
    post,
    read_all,
    seen,
    subscribe,
    unsubscribe,
)
from trainer.services.programs import MAX_ROW_ID
from trainer.storage.database import connect

router = APIRouter(prefix="/api")


def _database(request: Request) -> str:
    return str(request.app.state.settings.database)


def _now() -> datetime:
    return datetime.now(UTC)


class PushKeyOut(BaseModel):
    """The server's VAPID public key, which a browser subscribes with."""

    key: str


def _push_key(request: Request) -> str:
    key: str | None = request.app.state.settings.push_key
    if key is None:
        raise HTTPException(status_code=503, detail="notifications are not set up")
    return key


@router.get("/push/key")
def push_key(request: Request) -> PushKeyOut:
    """The key to subscribe with; 503 until push is set up on the server."""
    return PushKeyOut(key=_push_key(request))


@router.put("/push/subscription", status_code=204)
def put_subscription(request: Request, body: SubscriptionIn) -> Response:
    """Push to this browser (idempotent: subscribing again replaces its keys).

    409 if it subscribed with another server key (one since replaced): the
    browser must subscribe again with the current one.
    """
    key = _push_key(request)
    with closing(connect(_database(request))) as conn:
        try:
            subscribe(conn, body, key, _now())
        except OtherServerKeyError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=204)


@router.delete("/push/subscription", status_code=204)
def delete_subscription(
    request: Request, endpoint: Annotated[str, Query(max_length=MAX_ENDPOINT_LENGTH)]
) -> Response:
    """Stop pushing to the browser at ``endpoint`` (idempotent)."""
    with closing(connect(_database(request))) as conn:
        unsubscribe(conn, endpoint)
    return Response(status_code=204)


class NoticeOut(BaseModel):
    """A notice in the inbox, and the screen it opens."""

    id: int
    kind: NoticeKind
    title: str
    body: str
    at: str
    read: bool
    route: str


class InboxOut(BaseModel):
    """The newest notices, newest first, and how many are unread."""

    unread: int
    notices: list[NoticeOut]


@router.get("/inbox")
def get_inbox(request: Request) -> InboxOut:
    """The inbox; a notice still held for the app to claim is not in it yet."""
    with closing(connect(_database(request))) as conn:
        shown = inbox(conn, _now())
    return InboxOut(
        unread=shown.unread,
        notices=[
            NoticeOut(
                id=notice.id,
                kind=notice.kind,
                title=notice.title,
                body=notice.body,
                at=notice.at,
                read=notice.read,
                route=ROUTES[notice.kind],
            )
            for notice in shown.notices
        ],
    )


@router.post("/inbox/{notice_id}/seen", status_code=204)
def post_seen(request: Request, notice_id: Annotated[int, Path(ge=1, le=MAX_ROW_ID)]) -> Response:
    """The owner has seen what notice ``notice_id`` is about: claim it, or mark it read."""
    with closing(connect(_database(request))) as conn:
        try:
            seen(conn, notice_id, _now())
        except NoticeNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.post("/inbox/read", status_code=204)
def post_read_all(request: Request) -> Response:
    """Mark every notice in the inbox read."""
    with closing(connect(_database(request))) as conn:
        read_all(conn, _now())
    return Response(status_code=204)


class PostedOut(BaseModel):
    """The id of a notice just posted."""

    id: int


@router.post("/push/test", status_code=201)
def post_test(request: Request) -> PostedOut:
    """Post a test notice: in the inbox at once, and pushed to every subscribed browser."""
    with closing(connect(_database(request))) as conn:
        return PostedOut(id=post(conn, TEST_NOTICE, _now()))
