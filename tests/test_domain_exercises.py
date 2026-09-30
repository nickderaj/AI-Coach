"""Exercise naming and measures."""

import pytest

from trainer.domain.exercises import Measure, normalise_name


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Lat Pulldown", "lat pulldown"),
        ("  lat \t pulldown\n", "lat pulldown"),
        ("", ""),
    ],
)
def test_normalise_name(text: str, expected: str) -> None:
    assert normalise_name(text) == expected


def test_measure_values_match_the_schema() -> None:
    assert [measure.value for measure in Measure] == ["reps", "seconds", "distance"]
