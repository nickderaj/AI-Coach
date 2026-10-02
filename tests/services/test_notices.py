"""The inbox, claiming a held notice, subscriptions and pushing."""

import base64
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, override

import pytest
from pydantic import ValidationError

from trainer.domain.notices import TEST_NOTICE, Notice, NoticeKind
from trainer.services.notices import (
    HOLD,
    INBOX_LIMIT,
    STALE_AFTER,
    Delivery,
    Inbox,
    NoticeNotFoundError,
    OtherServerKeyError,
    PushOutcome,
    SubscriptionIn,
    decode_key,
    deliver,
    inbox,
    is_push_endpoint,
    payload,
    post,
    read_all,
    seen,
    subscribe,
    unsubscribe,
)
from trainer.storage.database import connect
from trainer.storage.notices import StoredNotice, Subscription, list_subscriptions

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
COACH = Notice(NoticeKind.COACH, "Your coach answered", "Rest tomorrow.")
APPLE = "https://web.push.apple.com/QGuT8ar"
GOOGLE = "https://fcm.googleapis.com/fcm/send/dX3"


def b64(data: bytes, *, padded: bool = False) -> str:
    text = base64.urlsafe_b64encode(data).decode()
    return text if padded else text.rstrip("=")


P256DH = b64(b"\x04" + bytes(range(64)))
AUTH = b64(bytes(range(16)))
# The server's public key: the one browsers subscribe with, and pushes are signed with.
SERVER = b64(b"\x04" + bytes(range(1, 65)))


def subscription(endpoint: str = APPLE, server_key: str = SERVER, **keys: str) -> SubscriptionIn:
    return SubscriptionIn.model_validate(
        {
            "endpoint": endpoint,
            "keys": {"p256dh": P256DH, "auth": AUTH, **keys},
            "server_key": server_key,
        }
    )


class FakeSender:
    """Records each push; answers from a script by endpoint, else delivered."""

    def __init__(
        self, outcomes: dict[str, PushOutcome] | None = None, server_key: str = SERVER
    ) -> None:
        """Delivered everywhere unless ``outcomes`` says otherwise."""
        self.outcomes = outcomes or {}
        self.server_key = server_key
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:
        self.sent.append((subscription.endpoint, json.loads(payload)))
        return self.outcomes.get(subscription.endpoint, PushOutcome.DELIVERED)


# ---------------------------------------------------------------- the inbox


def test_a_notice_is_in_the_inbox_at_once_unless_held(db: sqlite3.Connection) -> None:
    now_id = post(db, TEST_NOTICE, NOW)
    held_id = post(db, COACH, NOW, HOLD)

    assert timedelta(seconds=15) == HOLD
    assert not db.in_transaction
    assert inbox(db, NOW) == Inbox(
        1,
        [
            StoredNotice(
                now_id,
                NoticeKind.TEST,
                "Notifications are on",
                "This is how the trainer will reach you.",
                "2026-10-02T09:00:00+00:00",
                read=False,
            )
        ],
    )
    later = inbox(db, NOW + HOLD)
    assert (later.unread, [notice.id for notice in later.notices]) == (2, [held_id, now_id])


def test_the_inbox_shows_the_newest_notices_and_counts_all_unread(
    db: sqlite3.Connection,
) -> None:
    for minute in range(INBOX_LIMIT + 1):
        post(db, COACH, NOW + timedelta(minutes=minute))

    shown = inbox(db, NOW + timedelta(hours=1))

    assert INBOX_LIMIT == 50
    assert shown.unread == INBOX_LIMIT + 1
    assert len(shown.notices) == INBOX_LIMIT
    assert shown.notices[0].at == "2026-10-02T09:50:00+00:00"


def test_a_held_notice_seen_in_the_app_is_claimed(db: sqlite3.Connection) -> None:
    notice = post(db, COACH, NOW, HOLD)

    seen(db, notice, NOW + HOLD - timedelta(seconds=1))

    assert not db.in_transaction
    assert inbox(db, NOW + HOLD) == Inbox(0, [])
    sender = FakeSender()
    subscribe(db, subscription(), SERVER, NOW)
    assert deliver(db, sender, NOW + HOLD) == Delivery()
    assert sender.sent == []


def test_a_notice_seen_once_due_is_marked_read(db: sqlite3.Connection) -> None:
    notice = post(db, COACH, NOW, HOLD)

    seen(db, notice, NOW + HOLD)

    shown = inbox(db, NOW + HOLD)
    assert shown.unread == 0
    assert [(n.id, n.read) for n in shown.notices] == [(notice, True)]


def test_seeing_an_unknown_notice_is_an_error(db: sqlite3.Connection) -> None:
    with pytest.raises(NoticeNotFoundError, match=r"^no notice has id 7$"):
        seen(db, 7, NOW)

    assert not db.in_transaction


def test_read_all_marks_what_is_shown(db: sqlite3.Connection) -> None:
    post(db, COACH, NOW)
    held = post(db, COACH, NOW, HOLD)

    read_all(db, NOW)

    assert not db.in_transaction
    assert inbox(db, NOW).unread == 0
    assert inbox(db, NOW + HOLD).unread == 1
    seen(db, held, NOW + HOLD)
    assert inbox(db, NOW + HOLD).unread == 0


# ---------------------------------------------------------------- subscriptions


@pytest.mark.parametrize(
    "url",
    [
        "https://web.push.apple.com/QGuT8ar",
        "https://push.apple.com/x",
        "https://fcm.googleapis.com/fcm/send/dX3",
        "https://updates.push.services.mozilla.com/wpush/v2/gAAA",
        "https://wns2-par02p.notify.windows.com/w/?token=BQYAAA",
    ],
)
def test_push_service_addresses(url: str) -> None:
    assert is_push_endpoint(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://web.push.apple.com/x",  # not HTTPS
        "https://push.apple.com.example.com/x",  # a lookalike
        "https://evilpush.apple.com.evil/x",
        "https://notpush.apple.com/x",  # not a subdomain
        "https://example.com/push.apple.com",
        "https://web.push.apple.com:8443/x",  # a port
        "https://web.push.apple.com:443/x",
        # A user, written apart so it does not read as an email address.
        "https://user" + "@web.push.apple.com/x",
        "https://:" + "@web.push.apple.com/x",
        "https://web.push.apple.com:bad/x",  # not a port
        "https://[::1/x",  # not a URL
        "https:///x",
        "",
    ],
)
def test_other_addresses_are_refused(url: str) -> None:
    assert not is_push_endpoint(url)


def test_decode_key_takes_padded_and_unpadded_base64url() -> None:
    data = b"\xfb\xff\x00"  # encodes to characters that differ from plain base64

    assert decode_key(b64(data)) == data
    assert decode_key(b64(data + b"x")) == data + b"x"
    assert decode_key(b64(data + b"x", padded=True)) == data + b"x"


@pytest.mark.parametrize("text", ["a", "é", "!", "AA!A", "a+b/", "AA=A", "AA===", "A" * 5])
def test_decode_key_refuses_what_is_not_base64url(text: str) -> None:
    with pytest.raises(ValueError, match=r"^not base64url$"):
        decode_key(text)


def test_a_browser_subscribes_and_resubscribes(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(), SERVER, NOW)
    subscribe(db, subscription(auth=b64(bytes(16))), SERVER, NOW)

    assert not db.in_transaction
    assert list_subscriptions(db) == [Subscription(APPLE, P256DH, b64(bytes(16)), SERVER)]


def test_padded_keys_are_kept_as_given(db: sqlite3.Connection) -> None:
    padded = b64(bytes(16), padded=True)

    subscribe(db, subscription(auth=padded), SERVER, NOW)

    assert list_subscriptions(db)[0].auth == padded


def test_a_browser_unsubscribes(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(), SERVER, NOW)

    assert unsubscribe(db, APPLE)
    assert not unsubscribe(db, APPLE)
    assert not db.in_transaction
    assert list_subscriptions(db) == []


@pytest.mark.parametrize(
    ("body", "where"),
    [
        ({"endpoint": "https://example.com/x"}, "endpoint"),
        ({"endpoint": APPLE + "x" * 2048}, "endpoint"),
        ({"p256dh": b64(b"\x04" + bytes(63))}, "p256dh"),  # too short
        ({"p256dh": b64(b"\x04" + bytes(65))}, "p256dh"),  # too long
        ({"p256dh": b64(b"\x05" + bytes(64))}, "p256dh"),  # not an uncompressed point
        ({"p256dh": "a" * 129}, "p256dh"),
        ({"p256dh": P256DH + "!"}, "p256dh"),
        ({"auth": b64(bytes(15))}, "auth"),
        ({"auth": b64(bytes(17))}, "auth"),
        ({"auth": AUTH + "==="}, "auth"),
        ({"auth": "a"}, "auth"),  # not base64url at all
        ({"auth": ""}, "auth"),
        ({"extra": "x"}, "extra"),
        ({"server_key": b64(b"\x04" + bytes(63))}, "server_key"),
        ({"server_key": b64(b"\x05" + bytes(64))}, "server_key"),
        ({"server_key": ""}, "server_key"),
        ({"expirationTime": None}, "expirationTime"),
    ],
)
def test_bad_subscriptions_are_refused(body: dict[str, Any], where: str) -> None:
    keys = {"p256dh": P256DH, "auth": AUTH}
    outer: dict[str, Any] = {"endpoint": APPLE, "server_key": SERVER}
    for key, value in body.items():
        (outer if key in {"endpoint", "expirationTime", "server_key"} else keys)[key] = value

    with pytest.raises(ValidationError, match=where):
        SubscriptionIn.model_validate({**outer, "keys": keys})


def test_the_longest_endpoint_and_key_are_accepted() -> None:
    endpoint = APPLE + "x" * (2048 - len(APPLE))

    assert subscription(endpoint).endpoint == endpoint
    assert subscription(p256dh=b64(b"\x04" + bytes(64), padded=True)).keys.p256dh.endswith("=")


def test_the_reasons_name_the_problem() -> None:
    with pytest.raises(ValidationError) as caught:
        subscription("https://example.com/x", p256dh=b64(bytes(65)), auth=b64(bytes(3)))

    messages = {error["loc"][-1]: error["msg"] for error in caught.value.errors()}
    assert messages == {
        "endpoint": "Value error, not a push service address",
        "p256dh": "Value error, must be 65 bytes",
        "auth": "Value error, must be 16 bytes",
    }


# ---------------------------------------------------------------- pushing


def test_the_payload_carries_the_notice_and_its_screen() -> None:
    notice = StoredNotice(
        3, NoticeKind.PROPOSAL, "Your coach proposed Upper", "Né", "t", read=False
    )

    assert payload(notice) == (
        b'{"id":3,"title":"Your coach proposed Upper","body":"N\\u00e9","route":"#/program"}'
    )


def test_due_notices_are_pushed_to_every_browser_once(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(APPLE), SERVER, NOW)
    subscribe(db, subscription(GOOGLE), SERVER, NOW)
    first = post(db, TEST_NOTICE, NOW)
    second = post(db, COACH, NOW, HOLD)
    sender = FakeSender()

    assert deliver(db, sender, NOW) == Delivery(delivered=2)
    assert deliver(db, sender, NOW + HOLD) == Delivery(delivered=2)
    assert deliver(db, sender, NOW + HOLD) == Delivery()

    assert not db.in_transaction
    assert [(endpoint, sent["id"]) for endpoint, sent in sender.sent] == [
        (APPLE, first),
        (GOOGLE, first),
        (APPLE, second),
        (GOOGLE, second),
    ]
    assert sender.sent[2][1] == {
        "id": second,
        "title": "Your coach answered",
        "body": "Rest tomorrow.",
        "route": "#/coach",
    }
    sent_at = [row[0] for row in db.execute("SELECT sent_at FROM inbox ORDER BY id")]
    assert sent_at == ["2026-10-02T09:00:00+00:00", "2026-10-02T09:00:15+00:00"]


def test_a_failed_push_is_not_retried_and_stays_in_the_inbox(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(APPLE), SERVER, NOW)
    subscribe(db, subscription(GOOGLE), SERVER, NOW)
    post(db, COACH, NOW)
    sender = FakeSender({APPLE: PushOutcome.FAILED})

    assert deliver(db, sender, NOW) == Delivery(delivered=1, failed=1)
    assert deliver(db, sender, NOW) == Delivery()

    assert len(list_subscriptions(db)) == 2
    assert inbox(db, NOW).unread == 1


def test_an_ended_subscription_is_forgotten(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(APPLE), SERVER, NOW)
    subscribe(db, subscription(GOOGLE), SERVER, NOW)
    post(db, COACH, NOW)
    post(db, COACH, NOW)

    first = deliver(db, FakeSender({APPLE: PushOutcome.GONE}), NOW)

    assert first == Delivery(delivered=2, gone=1)
    assert [s.endpoint for s in list_subscriptions(db)] == [GOOGLE]
    assert not db.in_transaction


def test_without_browsers_notices_wait_in_the_inbox(db: sqlite3.Connection) -> None:
    post(db, COACH, NOW)

    assert deliver(db, FakeSender(), NOW) == Delivery()

    subscribe(db, subscription(), SERVER, NOW)
    sender = FakeSender()
    assert deliver(db, sender, NOW) == Delivery()  # it was dealt with: never pushed late
    assert inbox(db, NOW).unread == 1


def test_a_notice_read_before_its_push_is_not_pushed(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(), SERVER, NOW)
    notice = post(db, COACH, NOW)
    seen(db, notice, NOW)
    sender = FakeSender()

    assert deliver(db, sender, NOW) == Delivery()
    assert sender.sent == []


def test_a_stale_notice_is_left_to_the_inbox(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(), SERVER, NOW)
    post(db, COACH, NOW - STALE_AFTER - timedelta(seconds=1))
    on_time = post(db, COACH, NOW - STALE_AFTER)
    sender = FakeSender()

    assert timedelta(hours=1) == STALE_AFTER
    assert deliver(db, sender, NOW) == Delivery(delivered=1)
    assert [sent["id"] for _, sent in sender.sent] == [on_time]
    assert db.execute("SELECT count(*) FROM inbox WHERE sent_at IS NULL").fetchone()[0] == 0


def test_overlapping_rounds_push_each_notice_once(db: sqlite3.Connection, tmp_path: Path) -> None:
    subscribe(db, subscription(), SERVER, NOW)
    first = post(db, COACH, NOW)
    second = post(db, TEST_NOTICE, NOW)
    other = FakeSender()

    class Overlapping(FakeSender):
        """While its first push is on its way, another round runs, on its own connection."""

        @override
        def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:
            if not self.sent:
                with closing(connect(tmp_path / "trainer.db")) as conn:
                    deliver(conn, other, NOW)
            return super().send(subscription, payload)

    outer = Overlapping()
    deliver(db, outer, NOW)

    pushed = [sent["id"] for _, sent in outer.sent + other.sent]
    assert sorted(pushed) == [first, second]


def test_a_round_cut_short_never_pushes_a_notice_twice(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(), SERVER, NOW)
    post(db, COACH, NOW)

    class Killed(FakeSender):
        """The process dies once the push has gone, before anything else."""

        @override
        def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:
            super().send(subscription, payload)
            raise SystemExit

    with pytest.raises(SystemExit):
        deliver(db, Killed(), NOW)
    db.rollback()  # what a fresh process would see

    again = FakeSender()
    assert deliver(db, again, NOW) == Delivery()
    assert again.sent == []


def test_a_notice_read_after_it_was_selected_is_not_pushed(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    subscribe(db, subscription(), SERVER, NOW)
    post(db, COACH, NOW)
    second = post(db, TEST_NOTICE, NOW)

    class ReadMeanwhile(FakeSender):
        """While the first notice is pushed, the app marks the second read, through the API."""

        @override
        def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:
            with closing(connect(tmp_path / "trainer.db")) as api:
                seen(api, second, NOW)
            return super().send(subscription, payload)

    sender = ReadMeanwhile()
    assert deliver(db, sender, NOW) == Delivery(delivered=1)

    assert [sent["id"] for _, sent in sender.sent] == [second - 1]
    assert db.execute("SELECT sent_at FROM inbox WHERE id = ?", (second,)).fetchone()[0] == (
        "2026-10-02T09:00:00+00:00"
    )


def test_a_subscription_made_with_another_server_key_is_refused(db: sqlite3.Connection) -> None:
    old = b64(b"\x04" + bytes(64))

    with pytest.raises(
        OtherServerKeyError, match=r"^subscribed with another server key; subscribe again$"
    ):
        subscribe(db, subscription(server_key=old), SERVER, NOW)

    assert list_subscriptions(db) == []
    assert not db.in_transaction


def test_the_server_key_compares_by_value_not_padding(db: sqlite3.Connection) -> None:
    padded = b64(b"\x04" + bytes(range(1, 65)), padded=True)

    subscribe(db, subscription(server_key=padded), SERVER, NOW)

    assert list_subscriptions(db)[0].server_key == SERVER  # stored as the server has it


def test_a_new_server_key_forgets_the_old_subscriptions(db: sqlite3.Connection) -> None:
    subscribe(db, subscription(APPLE), SERVER, NOW)
    new = b64(b"\x04" + bytes(range(2, 66)))
    subscribe(db, subscription(GOOGLE, server_key=new), new, NOW)
    post(db, COACH, NOW)
    sender = FakeSender(server_key=new)

    assert deliver(db, sender, NOW) == Delivery(delivered=1, gone=1)

    assert [endpoint for endpoint, _ in sender.sent] == [GOOGLE]
    assert [s.endpoint for s in list_subscriptions(db)] == [GOOGLE]
