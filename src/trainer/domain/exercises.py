"""Exercise identity: how exercises are named, matched and measured."""

from __future__ import annotations

from difflib import SequenceMatcher
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Names at least this similar (difflib ratio) are flagged as near-duplicates.
SIMILARITY_THRESHOLD = 0.85
# Plural "s" is folded only on words longer than this ("press" -> "pres" is harmless,
# but "abs" must stay "abs").
MIN_PLURAL_LENGTH = 3


class Measure(StrEnum):
    """What one set of an exercise records."""

    REPS = "reps"
    SECONDS = "seconds"
    DISTANCE = "distance"


class Equipment(StrEnum):
    """What the exercise is done with; part of its identity (D9)."""

    BARBELL = "barbell"
    DUMBBELL = "dumbbell"
    KETTLEBELL = "kettlebell"
    CABLE = "cable"
    MACHINE = "machine"
    BODYWEIGHT = "bodyweight"
    EZ_BAR = "ez bar"
    BAND = "band"
    OTHER = "other"


def normalise_name(text: str) -> str:
    """The lookup key for an exercise name or alias: lower case, single spaces."""
    return " ".join(text.lower().split())


def _tokens(name: str) -> frozenset[str]:
    """Words of a name with a trailing plural "s" folded ("raises" == "raise")."""
    return frozenset(
        word[:-1] if len(word) > MIN_PLURAL_LENGTH and word.endswith("s") else word
        for word in normalise_name(name).replace("-", " ").split()
    )


def is_near_duplicate(candidate: str, existing: str) -> bool:
    """Whether ``candidate`` probably names the same exercise as ``existing``.

    True when the words match up to plurals and hyphens, when one name's words
    are all contained in the other's ("bench press" vs "barbell bench press"),
    or when the spellings are very close ("lat pulldown" vs "lat pull down").
    """
    left, right = _tokens(candidate), _tokens(existing)
    if not left - right or not right - left:  # one name has no words the other lacks
        return True
    ratio = SequenceMatcher(None, normalise_name(candidate), normalise_name(existing)).ratio()
    return ratio >= SIMILARITY_THRESHOLD


def near_duplicates(candidate: str, names: Iterable[tuple[int, str]]) -> list[int]:
    """Ids of every ``(id, name)`` the candidate may duplicate, each id once, in order."""
    found: list[int] = []
    for exercise_id, name in names:
        if exercise_id not in found and is_near_duplicate(candidate, name):
            found.append(exercise_id)
    return found
