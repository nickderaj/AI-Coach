"""Notices: what the app tells the owner, in the inbox and as a push.

Only two things are worth interrupting the owner for: the coach answered while
they were away, and that answer came with a program to look at. Nothing is
sent on a schedule; the program's next day is on Today and Home already.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# The longest preview of a reply; a push shows a few lines at most.
PREVIEW_LENGTH = 140
ELLIPSIS = "…"


class NoticeKind(StrEnum):
    """What a notice is about, which decides the screen it opens."""

    COACH = "coach"  # the coach answered
    PROPOSAL = "proposal"  # the coach answered with a program to accept or turn down
    TEST = "test"  # sent from Settings to check notifications work


# The screen of the web app each kind of notice opens.
ROUTES = {
    NoticeKind.COACH: "#/coach",
    NoticeKind.PROPOSAL: "#/program",
    NoticeKind.TEST: "#/inbox",
}


@dataclass(frozen=True)
class Notice:
    """A notice to post: its kind, a title and a line or two of text."""

    kind: NoticeKind
    title: str
    body: str


def preview(text: str, limit: int = PREVIEW_LENGTH) -> str:
    """``text`` on one line, cut at a word to at most ``limit`` characters."""
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    # One character more than fits beside the ellipsis, to see whether a word ends there.
    cut = line[:limit]
    head = cut.rsplit(" ", 1)[0] if " " in cut else cut[:-1]
    return head.rstrip(",.;:") + ELLIPSIS


def coach_answered(reply: str, proposal: str | None) -> Notice:
    """The notice for a coach's reply; ``proposal`` names a program it proposed."""
    if proposal is None:
        return Notice(NoticeKind.COACH, "Your coach answered", preview(reply))
    return Notice(NoticeKind.PROPOSAL, f"Your coach proposed {proposal}", preview(reply))


TEST_NOTICE = Notice(
    NoticeKind.TEST, "Notifications are on", "This is how the trainer will reach you."
)
