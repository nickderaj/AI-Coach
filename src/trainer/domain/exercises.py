"""Exercise identity: how exercises are named, matched and measured."""

from __future__ import annotations

from enum import StrEnum


class Measure(StrEnum):
    """What one set of an exercise records."""

    REPS = "reps"
    SECONDS = "seconds"
    DISTANCE = "distance"


def normalise_name(text: str) -> str:
    """The lookup key for an exercise name or alias: lower case, single spaces."""
    return " ".join(text.lower().split())
