"""The inbox table and push subscriptions."""

import sqlite3

import pytest

from trainer.domain.notices import Notice, NoticeKind
from trainer.storage.notices import (
    StoredNotice,
    Subscription,
    claim_unsent,
    delete_held_notice,
    delete_subscription,
    insert_notice,
    list_subscriptions,
    mark_all_read,
    mark_read,
    save_subscription,
    shown_notices,
    unread_count,
    unsent_notices,
)

T0 = "2026-10-02T09:00:00+00:00"
T1 = "2026-10-02T09:00:15+00:00"
T2 = "2026-10-02T09:01:00+00:00"
COACH = Notice(NoticeKind.COACH, "Your coach answered", "Rest tomorrow.")
TEST = Notice(NoticeKind.TEST, "Notifications are on", "")
INBOX = "INSERT INTO inbox (kind, title, body, created_at, due_at)"
APPLE = Subscription("https://web.push.apple.com/one", "BKey", "auth")


def test_a_notice_shows_from_when_it_is_due(db: sqlite3.Connection) -> None:
    held = insert_notice(db, COACH, T0, T1)

    assert shown_notices(db, T0, 10) == []
    assert unread_count(db, T0) == 0
    assert shown_notices(db, T1, 10) == [
        StoredNotice(
            held, NoticeKind.COACH, "Your coach answered", "Rest tomorrow.", T1, read=False
        )
    ]
    assert unread_count(db, T1) == 1


def test_the_inbox_is_newest_first_and_limited(db: sqlite3.Connection) -> None:
    first = insert_notice(db, COACH, T0, T0)
    second = insert_notice(db, TEST, T0, T0)  # same time: the later id is newer
    third = insert_notice(db, TEST, T1, T1)

    assert [notice.id for notice in shown_notices(db, T2, 10)] == [third, second, first]
    assert [notice.id for notice in shown_notices(db, T2, 2)] == [third, second]


def test_only_a_held_notice_can_be_claimed(db: sqlite3.Connection) -> None:
    notice = insert_notice(db, COACH, T0, T1)

    assert not delete_held_notice(db, notice, T1)  # due now: no longer held
    assert delete_held_notice(db, notice, T0)
    assert not delete_held_notice(db, notice, T0)
    assert db.execute("SELECT count(*) FROM inbox").fetchone()[0] == 0


def test_marking_read_keeps_the_first_time(db: sqlite3.Connection) -> None:
    notice = insert_notice(db, COACH, T0, T0)

    assert mark_read(db, notice, T1)
    assert mark_read(db, notice, T2)
    assert not mark_read(db, notice + 1, T2)

    assert db.execute("SELECT read_at FROM inbox").fetchone()[0] == T1
    assert shown_notices(db, T2, 10)[0].read
    assert unread_count(db, T2) == 0


def test_mark_all_read_leaves_held_and_read_notices(db: sqlite3.Connection) -> None:
    read = insert_notice(db, COACH, T0, T0)
    mark_read(db, read, T0)
    unread = insert_notice(db, TEST, T0, T0)
    held = insert_notice(db, COACH, T0, T2)

    mark_all_read(db, T1)

    rows = dict(db.execute("SELECT id, read_at FROM inbox").fetchall())
    assert rows == {read: T0, unread: T1, held: None}


def test_unsent_notices_are_due_and_oldest_first(db: sqlite3.Connection) -> None:
    later = insert_notice(db, COACH, T1, T1)
    sent = insert_notice(db, TEST, T0, T0)
    assert claim_unsent(db, sent, T0)
    assert not claim_unsent(db, sent, T1)  # taken already: the first time stays
    earlier = insert_notice(db, TEST, T0, T0)
    insert_notice(db, COACH, T0, T2)  # held

    assert [notice.id for notice in unsent_notices(db, T1)] == [earlier, later]
    assert db.execute("SELECT sent_at FROM inbox WHERE id = ?", (sent,)).fetchone()[0] == T0


def test_a_subscription_is_saved_once_per_endpoint(db: sqlite3.Connection) -> None:
    save_subscription(db, APPLE, T0)
    save_subscription(db, Subscription(APPLE.endpoint, "BNew", "fresh"), T1)
    other = Subscription("https://fcm.googleapis.com/fcm/send/x", "BOther", "a2")
    save_subscription(db, other, T1)

    assert list_subscriptions(db) == [Subscription(APPLE.endpoint, "BNew", "fresh"), other]
    created = db.execute("SELECT created_at FROM push_subscriptions ORDER BY id").fetchall()
    assert [row[0] for row in created] == [T0, T1]


def test_a_subscription_can_be_removed(db: sqlite3.Connection) -> None:
    save_subscription(db, APPLE, T0)

    assert delete_subscription(db, APPLE.endpoint)
    assert not delete_subscription(db, APPLE.endpoint)
    assert list_subscriptions(db) == []


@pytest.mark.parametrize(
    "statement",
    [
        f"{INBOX} VALUES ('nag', 't', '', 'a', 'a')",
        f"{INBOX} VALUES ('test', '', '', 'a', 'a')",
        f"{INBOX} VALUES ('test', 't', '', 'b', 'a')",  # due before it was made
        f"{INBOX} VALUES ('test', 't', NULL, 'a', 'a')",
        (
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) "
            "VALUES ('http://push.example.com/x', 'k', 'a', 't')"
        ),
        (
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) "
            "VALUES ('https://push.example.com/x', '', 'a', 't')"
        ),
        (
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) "
            "VALUES ('https://push.example.com/x', 'k', '', 't')"
        ),
    ],
)
def test_the_tables_refuse_invalid_rows(db: sqlite3.Connection, statement: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(statement)


def test_every_kind_can_be_stored(db: sqlite3.Connection) -> None:
    for kind in NoticeKind:
        insert_notice(db, Notice(kind, "t", ""), T0, T0)

    assert {notice.kind for notice in shown_notices(db, T0, 10)} == set(NoticeKind)
