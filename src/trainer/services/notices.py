"""Notices for the owner: the inbox, and pushing them to subscribed browsers.

Every notice goes to the inbox, so nothing is lost when a push is missed or
notifications are off. A notice can be held for a moment first: if the app
shows the owner what it is about in that time, it claims the notice, which is
then neither kept nor pushed.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Protocol
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, field_validator

from trainer.domain.notices import ROUTES
from trainer.domain.times import utc_iso
from trainer.storage.database import write_transaction
from trainer.storage.notices import (
    StoredNotice,
    Subscription,
    delete_held_notice,
    delete_subscription,
    insert_notice,
    list_subscriptions,
    mark_all_read,
    mark_read,
    mark_sent,
    save_subscription,
    shown_notices,
    unread_count,
    unsent_notices,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from trainer.domain.notices import Notice

# How long a coach's answer waits for the app to claim it before it is pushed.
HOLD = timedelta(seconds=15)
# A push that could not go out within this long is left to the inbox.
STALE_AFTER = timedelta(hours=1)
# The most notices the inbox shows.
INBOX_LIMIT = 50
# The push services browsers subscribe through: Apple, Google, Mozilla, Microsoft.
# The sender talks to these hosts, and their subdomains, only.
PUSH_HOSTS = (
    "push.apple.com",
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
)
BASE64URL = re.compile(r"[A-Za-z0-9_-]*={0,2}")
MAX_ENDPOINT_LENGTH = 2048
P256DH_LENGTH = 65  # an uncompressed P-256 point
AUTH_LENGTH = 16


class NoticeNotFoundError(LookupError):
    """No notice has that id."""


def is_push_endpoint(url: str) -> bool:
    """Whether ``url`` is an HTTPS address on a known push service.

    No user, password or port is accepted: a push service needs none.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = parts.hostname
    if host is None:
        return False
    return (
        parts.scheme == "https"
        and port is None
        and "@" not in parts.netloc
        and any(host == known or host.endswith(f".{known}") for known in PUSH_HOSTS)
    )


def _endpoint(url: str) -> str:
    if not is_push_endpoint(url):
        message = "not a push service address"
        raise ValueError(message)
    return url


def decode_key(text: str) -> bytes:
    """The bytes of a browser's base64url key, padded or not.

    Raises:
        ValueError: if ``text`` is not base64url.
    """
    message = "not base64url"
    # The standard decoders skip characters outside the alphabet, or take "+"
    # and "/" as well: check the alphabet first.
    if not BASE64URL.fullmatch(text):
        raise ValueError(message)
    try:
        # Two "=" are as many as any length needs; the decoder ignores the rest.
        return base64.urlsafe_b64decode(text + "==")
    except ValueError as error:  # binascii.Error: a length no encoding has
        raise ValueError(message) from error


def _sized(text: str, length: int, first: bytes = b"") -> str:
    key = decode_key(text)
    if len(key) != length or not key.startswith(first):
        message = f"must be {length} bytes"
        raise ValueError(message)
    return text


Key = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class SubscriptionKeys(BaseModel):
    """A browser's keys for its pushes (``PushSubscription.toJSON().keys``)."""

    model_config = ConfigDict(extra="forbid")

    p256dh: Key
    auth: Key

    @field_validator("p256dh")
    @classmethod
    def _uncompressed_point(cls, text: str) -> str:
        return _sized(text, P256DH_LENGTH, b"\x04")

    @field_validator("auth")
    @classmethod
    def _secret(cls, text: str) -> str:
        return _sized(text, AUTH_LENGTH)


class SubscriptionIn(BaseModel):
    """A browser's push subscription, as it gives it."""

    model_config = ConfigDict(extra="forbid")

    endpoint: Annotated[
        str, StringConstraints(max_length=MAX_ENDPOINT_LENGTH), AfterValidator(_endpoint)
    ]
    keys: SubscriptionKeys


def subscribe(conn: sqlite3.Connection, subscription: SubscriptionIn, now: datetime) -> None:
    """Push notices to this browser from now on (again, if it subscribed before)."""
    keys = subscription.keys
    with write_transaction(conn):
        save_subscription(
            conn, Subscription(subscription.endpoint, keys.p256dh, keys.auth), utc_iso(now)
        )


def unsubscribe(conn: sqlite3.Connection, endpoint: str) -> bool:
    """Stop pushing to the browser at ``endpoint``; whether it was subscribed."""
    with write_transaction(conn):
        return delete_subscription(conn, endpoint)


def post(
    conn: sqlite3.Connection, notice: Notice, now: datetime, hold: timedelta = timedelta(0)
) -> int:
    """Put ``notice`` in the inbox, shown and pushed after ``hold``; return its id."""
    with write_transaction(conn):
        return insert_notice(conn, notice, utc_iso(now), utc_iso(now + hold))


def seen(conn: sqlite3.Connection, notice_id: int, now: datetime) -> None:
    """The owner has seen notice ``notice_id`` in the app.

    One still held is claimed: it is removed and never pushed. Any other is
    marked read.

    Raises:
        NoticeNotFoundError: if there is no such notice.
    """
    stamp = utc_iso(now)
    with write_transaction(conn):
        if not delete_held_notice(conn, notice_id, stamp) and not mark_read(conn, notice_id, stamp):
            message = f"no notice has id {notice_id}"
            raise NoticeNotFoundError(message)


def read_all(conn: sqlite3.Connection, now: datetime) -> None:
    """Mark every notice in the inbox read."""
    with write_transaction(conn):
        mark_all_read(conn, utc_iso(now))


@dataclass(frozen=True)
class Inbox:
    """The newest notices, newest first, and how many of all of them are unread."""

    unread: int
    notices: list[StoredNotice]


def inbox(conn: sqlite3.Connection, now: datetime) -> Inbox:
    """The inbox as it stands at ``now``; held notices are not in it yet."""
    stamp = utc_iso(now)
    return Inbox(unread_count(conn, stamp), shown_notices(conn, stamp, INBOX_LIMIT))


class PushOutcome(StrEnum):
    """What a push service made of one push."""

    DELIVERED = "delivered"
    GONE = "gone"  # the subscription has ended; stop pushing to it
    FAILED = "failed"  # refused or unreachable; the notice stays in the inbox


class PushSender(Protocol):
    """Encrypts and sends one push (``trainer.services.webpush``); never raises."""

    def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:
        """Push ``payload`` to ``subscription``."""
        ...


def payload(notice: StoredNotice) -> bytes:
    """What the service worker is sent: the notice, and the screen it opens."""
    fields = {
        "id": notice.id,
        "title": notice.title,
        "body": notice.body,
        "route": ROUTES[notice.kind],
    }
    return json.dumps(fields, separators=(",", ":")).encode()


@dataclass(frozen=True)
class Delivery:
    """What one round of pushing did: pushes delivered, failed, and browsers gone."""

    delivered: int = 0
    failed: int = 0
    gone: int = 0


def deliver(conn: sqlite3.Connection, sender: PushSender, now: datetime) -> Delivery:
    """Push every notice that has come due to every subscribed browser.

    Each notice is pushed once, whatever happens to it. A notice already read
    in the app, or due more than ``STALE_AFTER`` ago, is not pushed at all. A
    browser whose subscription has ended is forgotten. No transaction is held
    while a push is on its way.
    """
    stamp = utc_iso(now)
    stale = utc_iso(now - STALE_AFTER)
    total = Delivery()
    for notice in unsent_notices(conn, stamp):
        if not notice.read and notice.at >= stale:
            total = _sum(total, _push(conn, sender, notice))
        with write_transaction(conn):
            mark_sent(conn, notice.id, stamp)
    return total


def _push(conn: sqlite3.Connection, sender: PushSender, notice: StoredNotice) -> Delivery:
    body = payload(notice)
    outcomes = [
        (subscription, sender.send(subscription, body)) for subscription in list_subscriptions(conn)
    ]
    gone = [subscription for subscription, outcome in outcomes if outcome is PushOutcome.GONE]
    with write_transaction(conn):
        for subscription in gone:
            delete_subscription(conn, subscription.endpoint)
    results = [outcome for _, outcome in outcomes]
    return Delivery(
        results.count(PushOutcome.DELIVERED), results.count(PushOutcome.FAILED), len(gone)
    )


def _sum(one: Delivery, other: Delivery) -> Delivery:
    return Delivery(
        one.delivered + other.delivered, one.failed + other.failed, one.gone + other.gone
    )
