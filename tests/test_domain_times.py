"""UTC storage timestamps."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from trainer.domain.times import NaiveTimestampError, utc_iso

# Timestamps must not depend on the host's timezone (CI runs in UTC).
pytestmark = pytest.mark.usefixtures("far_east_timezone")


def test_converts_to_utc_with_seconds_precision() -> None:
    moment = datetime(2026, 9, 30, 8, 15, 30, 999_999, tzinfo=timezone(timedelta(hours=1)))

    assert utc_iso(moment) == "2026-09-30T07:15:30+00:00"


def test_utc_input_is_unchanged() -> None:
    assert utc_iso(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00+00:00"


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(NaiveTimestampError, match=r"^2026-01-01T00:00:00 has no timezone$"):
        utc_iso(datetime(2026, 1, 1))  # noqa: DTZ001  # why: exercising the naive case
