"""What the app tells the owner, and the screens notices open."""

import pytest

from trainer.domain.notices import (
    PREVIEW_LENGTH,
    ROUTES,
    TEST_NOTICE,
    Notice,
    NoticeKind,
    coach_answered,
    preview,
)


def test_each_kind_opens_its_screen() -> None:
    assert ROUTES == {
        NoticeKind.COACH: "#/coach",
        NoticeKind.PROPOSAL: "#/program",
        NoticeKind.TEST: "#/inbox",
    }
    assert [kind.value for kind in NoticeKind] == ["coach", "proposal", "test"]


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("Short and sweet.", 140, "Short and sweet."),
        ("  Two\n\nlines,\tspaced  out ", 140, "Two lines, spaced out"),
        ("abcdef", 6, "abcdef"),  # exactly the limit
        ("one two three", 8, "one two…"),  # a word ends one before the limit
        ("one two three", 9, "one two…"),
        ("one two three", 7, "one…"),
        ("one, two", 6, "one…"),  # no comma before the ellipsis
        ("one. two", 6, "one…"),
        ("one; two", 6, "one…"),
        ("one: two", 6, "one…"),
        ("A BOX of it", 8, "A BOX…"),
        ("abcdefgh", 5, "abcd…"),  # one long word is cut inside it
    ],
)
def test_preview_cuts_at_a_word(text: str, limit: int, expected: str) -> None:
    shown = preview(text, limit)

    assert shown == expected
    assert len(shown) <= limit


def test_a_preview_fits_a_push() -> None:
    long = "word " * 100

    assert PREVIEW_LENGTH == 140
    assert len(preview(long)) == 140  # 28 words and their spaces, then the ellipsis
    assert preview(long).endswith("word…")


def test_the_coach_answered() -> None:
    assert coach_answered("Rest\ntomorrow.", None) == Notice(
        NoticeKind.COACH, "Your coach answered", "Rest tomorrow."
    )


def test_the_coach_answered_with_a_program() -> None:
    assert coach_answered("Here is a\nnew block.", "Upper/Lower") == Notice(
        NoticeKind.PROPOSAL, "Your coach proposed Upper/Lower", "Here is a new block."
    )


def test_the_test_notice() -> None:
    expected = Notice(
        NoticeKind.TEST, "Notifications are on", "This is how the trainer will reach you."
    )

    assert expected == TEST_NOTICE
