"""The coach's durable session id."""

import sqlite3

import pytest

from trainer.storage.coach import read_session_id, save_session_id


def test_no_session_until_one_is_saved(db: sqlite3.Connection) -> None:
    assert read_session_id(db) is None


def test_saving_replaces_the_one_session(db: sqlite3.Connection) -> None:
    save_session_id(db, "api_1")
    save_session_id(db, "api_2")

    assert read_session_id(db) == "api_2"
    assert db.execute("SELECT count(*) FROM coach").fetchone()[0] == 1


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO coach (id, session_id) VALUES (2, 'x')",
        "INSERT INTO coach (id, session_id) VALUES (1, '')",
        "INSERT INTO coach (id, session_id) VALUES (1, NULL)",
    ],
)
def test_the_table_holds_one_real_session(db: sqlite3.Connection, statement: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(statement)
