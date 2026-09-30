"""The owner's profile."""

import sqlite3

from trainer.storage.profile import Profile, read_profile, save_profile


def test_empty_until_saved(db: sqlite3.Connection) -> None:
    assert read_profile(db) == Profile(None)


def test_saved_and_replaced(db: sqlite3.Connection) -> None:
    save_profile(db, Profile(65.0))
    save_profile(db, Profile(64.5))

    assert read_profile(db) == Profile(64.5)
    assert db.execute("SELECT count(*) FROM profile").fetchone()[0] == 1


def test_body_weight_can_be_cleared(db: sqlite3.Connection) -> None:
    save_profile(db, Profile(65.0))
    save_profile(db, Profile(None))

    assert read_profile(db) == Profile(None)
