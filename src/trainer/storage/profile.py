"""The owner's profile: one row of personal settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True)
class Profile:
    """Settings about the owner that the numbers depend on."""

    bodyweight_kg: float | None


def read_profile(conn: sqlite3.Connection) -> Profile:
    """The profile, empty until first saved."""
    row = conn.execute("""SELECT bodyweight_kg FROM profile WHERE id = 1""").fetchone()
    return Profile(None if row is None else row[0])


def save_profile(conn: sqlite3.Connection, profile: Profile) -> None:
    """Create or replace the profile."""
    conn.execute(
        """
        INSERT INTO profile (id, bodyweight_kg) VALUES (1, ?)
        ON CONFLICT (id) DO UPDATE SET bodyweight_kg = excluded.bodyweight_kg
        """,
        (profile.bodyweight_kg,),
    )
