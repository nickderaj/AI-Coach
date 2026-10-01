"""Program engine: double progression, deload and the next program day."""

import pytest

from trainer.domain.exercises import Equipment
from trainer.domain.programs import (
    LOAD_INCREMENTS,
    TRAINING_WEEKS,
    Decision,
    Position,
    Prescription,
    SetDone,
    Target,
    deload,
    is_deload_week,
    load_increment,
    next_position,
    progress,
    target_for,
    working_load,
)

# 3 sets of 8-10 at 10 kg first, in 2.5 kg steps.
BENCH = Prescription(sets=3, rep_min=8, rep_max=10, start_load_kg=10.0, increment_kg=2.5)


def sets(*done: tuple[float, float | None]) -> list[SetDone]:
    return [SetDone(amount, load) for amount, load in done]


def test_six_training_weeks() -> None:
    assert TRAINING_WEEKS == 6


@pytest.mark.parametrize(
    ("equipment", "increment"),
    [
        ("barbell", 2.5),
        ("dumbbell", 2.5),
        ("ez bar", 2.5),
        ("cable", 2.5),
        ("machine", 5.0),
        ("kettlebell", 4.0),
        ("bodyweight", 2.5),
        ("band", None),
        ("other", None),
        ("smith machine", None),  # not a known kind
        (None, None),
    ],
)
def test_load_increment_by_equipment(equipment: str | None, increment: float | None) -> None:
    assert load_increment(equipment, None) == increment


def test_every_loadable_equipment_has_an_increment() -> None:
    assert set(LOAD_INCREMENTS) == set(Equipment) - {Equipment.BAND, Equipment.OTHER}


@pytest.mark.parametrize("equipment", ["barbell", "band", None])
def test_an_exercises_own_increment_wins(equipment: str | None) -> None:
    assert load_increment(equipment, 1.25) == 1.25


def test_working_load_is_the_heaviest() -> None:
    assert working_load(sets((12, 5.0), (8, 12.5), (10, None))) == 12.5
    assert working_load(sets((12, None), (8, None))) is None
    assert working_load([]) is None


class TestProgress:
    def test_first_session_starts_at_the_programs_load_and_the_bottom(self) -> None:
        assert progress(BENCH, []) == Target(Decision.START, 10.0, (8, 8, 8))

    def test_first_session_without_a_starting_load_leaves_it_open(self) -> None:
        prescription = Prescription(4, 6, 8, None, 2.5)

        assert progress(prescription, []) == Target(Decision.START, None, (6, 6, 6, 6))

    def test_top_of_the_range_on_every_set_adds_an_increment_and_resets(self) -> None:
        # The owner's rule: 12 x 10 kg -> next time 12.5 kg for 8-10.
        last = sets((10, 10.0), (10, 10.0), (10, 10.0))

        assert progress(BENCH, last) == Target(Decision.PROGRESS, 12.5, (8, 8, 8))

    def test_going_past_the_top_counts_as_the_top(self) -> None:
        last = sets((12, 10.0), (11, 10.0), (10, 10.0))

        assert progress(BENCH, last).decision is Decision.PROGRESS

    def test_one_set_short_of_the_top_repeats(self) -> None:
        last = sets((10, 10.0), (10, 10.0), (9, 10.0))

        assert progress(BENCH, last) == Target(Decision.REPEAT, 10.0, (10, 10, 9))

    def test_fewer_sets_than_prescribed_repeats_even_at_the_top(self) -> None:
        last = sets((10, 10.0), (10, 10.0))

        assert progress(BENCH, last) == Target(Decision.REPEAT, 10.0, (10, 10, 8))

    def test_extra_sets_count_but_prefill_only_the_prescribed(self) -> None:
        last = sets((10, 10.0), (10, 10.0), (10, 10.0), (9, 10.0))

        assert progress(BENCH, last) == Target(Decision.REPEAT, 10.0, (10, 10, 10))

    def test_warm_ups_at_a_lighter_load_do_not_count(self) -> None:
        last = sets((5, 5.0), (10, 10.0), (10, 10.0), (10, 10.0))

        assert progress(BENCH, last) == Target(Decision.PROGRESS, 12.5, (8, 8, 8))

    def test_a_heavier_single_set_is_the_working_load(self) -> None:
        last = sets((10, 10.0), (10, 10.0), (8, 12.5))

        assert progress(BENCH, last) == Target(Decision.REPEAT, 12.5, (8, 8, 8))

    def test_repeat_prefills_last_times_amounts_within_the_range(self) -> None:
        last = sets((12, 10.0), (9, 10.0), (7, 10.0))

        assert progress(BENCH, last) == Target(Decision.REPEAT, 10.0, (10, 9, 8))

    def test_every_set_short_of_the_bottom_drops_an_increment(self) -> None:
        last = sets((7, 12.5), (6, 12.5), (5, 12.5))

        assert progress(BENCH, last) == Target(Decision.REDUCE, 10.0, (8, 8, 8))

    def test_one_set_in_the_range_is_not_a_failed_session(self) -> None:
        last = sets((8, 12.5), (6, 12.5), (5, 12.5))

        assert progress(BENCH, last) == Target(Decision.REPEAT, 12.5, (8, 8, 8))

    def test_a_drop_never_goes_below_no_load(self) -> None:
        prescription = Prescription(3, 8, 10, 1.0, 2.5)
        last = sets((5, 1.0), (5, 1.0), (5, 1.0))

        assert progress(prescription, last) == Target(Decision.REDUCE, 0.0, (8, 8, 8))

    def test_nothing_to_drop_at_no_load(self) -> None:
        prescription = Prescription(3, 8, 10, None, 2.5)

        assert progress(prescription, sets((5, 0.0), (5, 0.0), (5, 0.0))) == Target(
            Decision.REPEAT, 0.0, (8, 8, 8)
        )
        assert progress(prescription, sets((5, None), (5, None), (5, None))) == Target(
            Decision.REPEAT, None, (8, 8, 8)
        )

    def test_bodyweight_at_the_top_adds_load(self) -> None:
        pull_ups = Prescription(3, 6, 10, None, 2.5)
        last = sets((10, None), (10, None), (10, None))

        assert progress(pull_ups, last) == Target(Decision.PROGRESS, 2.5, (6, 6, 6))

    def test_without_an_increment_the_load_stays(self) -> None:
        band = Prescription(2, 10, 15, None, None)

        top = sets((15, 20.0), (15, 20.0))
        assert progress(band, top) == Target(Decision.REPEAT, 20.0, (15, 15))
        short = sets((5, 20.0), (5, 20.0))
        assert progress(band, short) == Target(Decision.REPEAT, 20.0, (10, 10))

    def test_timed_sets_progress_on_seconds(self) -> None:
        hang = Prescription(2, 30, 45, None, 2.5)

        assert progress(hang, sets((45.5, None), (45, None))).decision is Decision.PROGRESS
        assert progress(hang, sets((40.9, None), (45, None))) == Target(
            Decision.REPEAT, None, (40, 45)
        )

    def test_increments_add_exactly(self) -> None:
        prescription = Prescription(1, 5, 5, None, 1.25)

        assert progress(prescription, sets((5, 61.25))).load_kg == 62.5


class TestDeload:
    @pytest.mark.parametrize(
        ("prescribed", "deload_sets"),
        [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 4), (10, 6)],
    )
    def test_about_sixty_percent_of_the_sets(self, prescribed: int, deload_sets: int) -> None:
        prescription = Prescription(prescribed, 8, 10, 100.0, 2.5)

        target = deload(prescription, [])

        assert target.reps == (8,) * deload_sets

    @pytest.mark.parametrize(
        ("load", "increment", "deloaded"),
        [
            (100.0, 2.5, 90.0),
            (60.0, 2.5, 55.0),  # 54 is nearer 55 than 52.5
            (12.5, 2.5, 10.0),  # 11.25 is halfway: the lighter one
            (37.5, 2.5, 32.5),  # 33.75 is halfway: the lighter one, not the even one
            (40.0, 5.0, 35.0),  # 36 is nearer 35 than 40
        ],
    )
    def test_about_ninety_percent_of_the_load(
        self, load: float, increment: float | None, deloaded: float
    ) -> None:
        prescription = Prescription(3, 8, 10, None, increment)

        target = deload(prescription, sets((10, load), (10, load), (10, load)))

        assert target == Target(Decision.DELOAD, deloaded, (8, 8))

    @pytest.mark.parametrize("load", [20.0, 12.5])
    def test_without_an_increment_the_load_stays(self, load: float) -> None:
        # A band or "other" has no known steps: 90% may not be a load it has.
        # Fewer sets still make it a deload.
        band = Prescription(3, 15, 20, None, None)

        target = deload(band, sets((20, load), (20, load), (20, load)))

        assert target == Target(Decision.DELOAD, load, (15, 15))

    def test_from_the_last_working_load_not_the_start(self) -> None:
        target = deload(BENCH, sets((10, 5.0), (8, 20.0)))

        assert target.load_kg == 17.5

    def test_from_the_starting_load_when_never_done(self) -> None:
        assert deload(BENCH, []) == Target(Decision.DELOAD, 10.0, (8, 8))

    def test_without_any_load(self) -> None:
        prescription = Prescription(3, 6, 10, None, 2.5)

        assert deload(prescription, []) == Target(Decision.DELOAD, None, (6, 6))
        assert deload(prescription, sets((10, None))) == Target(Decision.DELOAD, None, (6, 6))


@pytest.mark.parametrize(("week", "deload_week"), [(1, False), (6, False), (7, True), (8, True)])
def test_is_deload_week(week: int, *, deload_week: bool) -> None:
    assert is_deload_week(week, 6) is deload_week


def test_target_for_picks_the_week_kind() -> None:
    last = sets((10, 20.0), (10, 20.0), (10, 20.0))  # not the starting load

    assert target_for(BENCH, last, deload_week=False) == progress(BENCH, last)
    assert target_for(BENCH, last, deload_week=True) == deload(BENCH, last)


class TestNextPosition:
    def test_a_new_program_starts_on_week_one_day_one(self) -> None:
        assert next_position(None, 4, 6) == Position(1, 1)

    def test_the_next_day_of_the_same_week(self) -> None:
        assert next_position(Position(1, 1), 4, 6) == Position(1, 2)
        assert next_position(Position(3, 3), 4, 6) == Position(3, 4)

    def test_after_the_last_day_the_next_week(self) -> None:
        assert next_position(Position(1, 4), 4, 6) == Position(2, 1)

    def test_after_the_last_training_week_the_deload_week(self) -> None:
        assert next_position(Position(6, 4), 4, 6) == Position(7, 1)
        assert next_position(Position(7, 3), 4, 6) == Position(7, 4)

    def test_after_the_deload_week_the_block_is_done(self) -> None:
        assert next_position(Position(7, 4), 4, 6) is None

    def test_a_one_day_program(self) -> None:
        assert next_position(Position(2, 1), 1, 6) == Position(3, 1)

    def test_a_missed_week_day_does_not_skip_ahead(self) -> None:
        # Days follow what was done: after Monday's day 1, a session on Thursday
        # is day 2, whatever the calendar says.
        done = [Position(1, 1)]
        for _ in range(9):
            following = next_position(done[-1], 3, 6)
            assert following is not None
            done.append(following)

        assert done[-1] == Position(4, 1)

    def test_a_whole_block_is_every_day_of_every_week_once(self) -> None:
        position = next_position(None, 3, 6)
        seen: list[Position] = []
        while position is not None:
            seen.append(position)
            position = next_position(position, 3, 6)

        assert seen == [Position(week, day) for week in range(1, 8) for day in range(1, 4)]
