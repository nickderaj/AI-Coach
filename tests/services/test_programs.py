"""Program use cases: proposals, accepting them, and planning today's day."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from itertools import count
from typing import Any

import pytest
from pydantic import ValidationError

from trainer.domain.exercises import Measure
from trainer.domain.programs import Decision, Position, Target
from trainer.services.journal import StaleProgramDayError, record_set, record_workout
from trainer.services.programs import (
    NoProposalError,
    PlannedExercise,
    ProgramError,
    ProgramIn,
    ProgramInUseError,
    SlotIn,
    accept_proposal,
    decline_proposal,
    programs,
    propose_program,
    today,
)
from trainer.storage.catalogue import ExerciseSpec, upsert_exercise
from trainer.storage.history import SetView
from trainer.storage.journal import ProgramLink, SetValues
from trainer.storage.profile import Profile, save_profile
from trainer.storage.programs import Program, ProgramStatus

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone(timedelta(hours=1)))

# Timestamps must not depend on the host's timezone (CI runs in UTC).
pytestmark = pytest.mark.usefixtures("far_east_timezone")


@pytest.fixture
def ids(db: sqlite3.Connection) -> dict[str, int]:
    catalogue = {
        "bench": ("barbell", Measure.REPS),
        "row": ("cable", Measure.REPS),
        "curl": ("dumbbell", Measure.REPS),
        "pull-up": ("bodyweight", Measure.REPS),
        "hang": ("bodyweight", Measure.SECONDS),
        "run": ("other", Measure.DISTANCE),
        "swim": ("other", Measure.DISTANCE),
    }
    found = {
        name: upsert_exercise(db, ExerciseSpec(name, name.title(), equipment, None, measure))
        for name, (equipment, measure) in catalogue.items()
    }
    db.commit()  # services open their own write transaction
    return found


def slot(
    exercise_id: int, sets: int = 3, reps: tuple[int, int] = (8, 10), **extra: object
) -> dict[str, Any]:
    return {
        "exercise_id": exercise_id,
        "sets": sets,
        "rep_min": reps[0],
        "rep_max": reps[1],
    } | extra


def body(ids: dict[str, int], name: str = "Upper/Lower") -> dict[str, Any]:
    return {
        "name": name,
        "notes": "two days",
        "days": [
            {
                "name": "Upper",
                "blocks": [
                    {
                        "rest_s": 120,
                        "exercises": [slot(ids["bench"], start_load_kg=60.0, notes="pause")],
                    },
                    {
                        "rest_s": 60,
                        "exercises": [
                            slot(ids["row"], reps=(10, 12)),
                            slot(ids["curl"], reps=(10, 12)),
                        ],
                    },
                ],
            },
            {
                "name": "Lower",
                "blocks": [
                    {"exercises": [slot(ids["pull-up"], reps=(6, 10))]},
                    {"exercises": [slot(ids["hang"], sets=2, reps=(30, 45))]},
                ],
            },
        ],
    }


def proposal(ids: dict[str, int], name: str = "Upper/Lower") -> ProgramIn:
    return ProgramIn.model_validate(body(ids, name))


class TestShape:
    def test_a_program(self, ids: dict[str, int]) -> None:
        program = proposal(ids)

        assert program.days[1].blocks[0].rest_s == 90  # the default rest
        assert program.days[0].blocks[0].exercises[0].start_load_kg == 60.0
        assert program.days[0].blocks[1].exercises[0].start_load_kg is None

    def test_text_is_trimmed(self) -> None:
        program = ProgramIn.model_validate(
            {
                "name": "  PPL ",
                "notes": " n ",
                "days": [{"name": " Push ", "blocks": [{"exercises": [slot(1, notes=" x ")]}]}],
            }
        )

        assert (program.name, program.notes, program.days[0].name) == ("PPL", "n", "Push")
        assert program.days[0].blocks[0].exercises[0].notes == "x"

    def test_a_range_of_one(self) -> None:
        assert slot_in(slot(1, reps=(5, 5))).rep_max == 5

    @pytest.mark.parametrize(
        "change",
        [
            {"rep_min": 9},  # above rep_max
            {"sets": 0},
            {"sets": 11},
            {"rep_min": 0},
            {"rep_max": 601},
            {"start_load_kg": -1},
            {"exercise_id": 0},
            {"exercise_id": 2**63},
            {"notes": "x" * 201},
            {"reps": 10},  # not a field
        ],
    )
    def test_a_bad_exercise(self, change: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            slot_in(slot(1, reps=(5, 8)) | change)

    @pytest.mark.parametrize(
        "program",
        [
            {"name": " ", "days": [{"name": "A", "blocks": [{"exercises": [slot(1)]}]}]},
            {"name": "P", "days": []},
            {"name": "P", "days": [{"name": "A", "blocks": [{"exercises": [slot(1)]}]}] * 8},
            {"name": "P", "days": [{"name": "A", "blocks": []}]},
            {"name": "P", "days": [{"name": "A", "blocks": [{"exercises": []}]}]},
            {"name": "P", "days": [{"name": "A", "blocks": [{"exercises": [slot(1)] * 4}]}]},
            {"name": "P", "days": [{"name": "A", "blocks": [{"exercises": [slot(1)]}] * 13}]},
            {
                "name": "P",
                "days": [{"name": "A", "blocks": [{"rest_s": 601, "exercises": [slot(1)]}]}],
            },
            {
                "name": "P",
                "weeks": 4,
                "days": [{"name": "A", "blocks": [{"exercises": [slot(1)]}]}],
            },
        ],
    )
    def test_a_bad_program(self, program: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            ProgramIn.model_validate(program)


def slot_in(data: dict[str, Any]) -> SlotIn:
    program = ProgramIn.model_validate(
        {"name": "P", "days": [{"name": "A", "blocks": [{"exercises": [data]}]}]}
    )
    return program.days[0].blocks[0].exercises[0]


class TestProposals:
    def test_propose_saves_a_proposal(self, db: sqlite3.Connection, ids: dict[str, int]) -> None:
        program = propose_program(db, proposal(ids), NOW)

        assert (program.name, program.notes, program.status) == (
            "Upper/Lower",
            "two days",
            ProgramStatus.PROPOSED,
        )
        assert (program.training_weeks, program.created_at, program.started_at) == (
            6,
            "2026-10-01T08:00:00+00:00",
            None,
        )
        assert [[len(block.exercises) for block in day.blocks] for day in program.days] == [
            [1, 2],
            [1, 1],
        ]
        assert program.days[0].blocks[0].exercises[0].notes == "pause"
        assert not db.in_transaction

    def test_a_new_proposal_replaces_the_last(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        first = propose_program(db, proposal(ids, "First"), NOW)

        second = propose_program(db, proposal(ids, "Second"), NOW)

        assert programs(db).proposed == second
        assert [tuple(row) for row in db.execute("SELECT name, status FROM programs")] == [
            ("First", "archived"),
            ("Second", "proposed"),
        ]
        assert first.id != second.id

    def test_unknown_exercises_are_refused(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        data = body(ids)
        data["days"][0]["blocks"][0]["exercises"] = [slot(98), slot(97), slot(98)]

        with pytest.raises(ProgramError, match=r"^no exercise has id 97, 98$"):
            propose_program(db, ProgramIn.model_validate(data), NOW)

        assert programs(db).proposed is None
        assert not db.in_transaction

    def test_distance_exercises_are_refused(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        data = body(ids)
        data["days"][1]["blocks"][1]["exercises"] = [slot(ids["swim"]), slot(ids["run"])]
        both = ", ".join(map(str, sorted([ids["run"], ids["swim"]])))

        with pytest.raises(ProgramError, match=rf"^exercise {both} is measured in distance$"):
            propose_program(db, ProgramIn.model_validate(data), NOW)

    def test_a_refused_proposal_keeps_the_last(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        kept = propose_program(db, proposal(ids), NOW)
        data = body(ids)
        data["days"][0]["blocks"][0]["exercises"] = [slot(99)]

        with pytest.raises(ProgramError):
            propose_program(db, ProgramIn.model_validate(data), NOW)

        assert programs(db).proposed == kept

    def test_decline_only_the_proposal_shown(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        shown = propose_program(db, proposal(ids, "Shown"), NOW)
        newer = propose_program(db, proposal(ids, "Newer"), NOW)  # the coach, meanwhile

        with pytest.raises(NoProposalError, match=rf"^program {shown.id} is not the proposal$"):
            decline_proposal(db, shown.id)

        assert programs(db).proposed == newer
        assert not db.in_transaction

    def test_a_replaced_or_declined_proposal_never_lends_its_id(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        first = propose_program(db, proposal(ids, "First"), NOW)
        second = propose_program(db, proposal(ids, "Second"), NOW)
        decline_proposal(db, second.id)
        third = propose_program(db, proposal(ids, "Third"), NOW)

        assert len({first.id, second.id, third.id}) == 3
        # A stale screen still showing the first or second cannot accept the third.
        for stale in (first.id, second.id):
            with pytest.raises(NoProposalError):
                accept_proposal(db, stale, NOW)

    def test_decline(self, db: sqlite3.Connection, ids: dict[str, int]) -> None:
        shown = propose_program(db, proposal(ids), NOW)

        decline_proposal(db, shown.id)

        assert programs(db).proposed is None
        status = db.execute("SELECT status FROM programs WHERE id = ?", (shown.id,)).fetchone()
        assert status[0] == "archived"
        assert not db.in_transaction
        with pytest.raises(NoProposalError):
            decline_proposal(db, shown.id)  # already gone

    def test_accept_starts_the_program(self, db: sqlite3.Connection, ids: dict[str, int]) -> None:
        proposed = propose_program(db, proposal(ids), NOW)

        accepted = accept_proposal(db, proposed.id, NOW + timedelta(hours=1))

        assert (accepted.id, accepted.status, accepted.started_at) == (
            proposed.id,
            ProgramStatus.ACTIVE,
            "2026-10-01T09:00:00+00:00",
        )
        assert programs(db).active == accepted
        assert programs(db).proposed is None
        assert not db.in_transaction

    def test_accept_archives_the_active_program(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        old = accept_proposal(db, propose_program(db, proposal(ids, "Old"), NOW).id, NOW)
        new = propose_program(db, proposal(ids, "New"), NOW)

        accept_proposal(db, new.id, NOW)

        assert db.execute("SELECT status FROM programs WHERE id = ?", (old.id,)).fetchone()[0] == (
            "archived"
        )
        active = programs(db).active
        assert active is not None
        assert active.name == "New"

    def test_a_program_in_progress_is_not_replaced(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        active = accept_proposal(db, propose_program(db, proposal(ids, "Old"), NOW).id, NOW)
        link = ProgramLink(active.days[0].id, 1)
        record_workout(db, "w1", (NOW, None), None, link)
        new = propose_program(db, proposal(ids, "New"), NOW)

        with pytest.raises(
            ProgramInUseError, match=r"^finish or discard the workout in progress first$"
        ):
            accept_proposal(db, new.id, NOW)

        assert not db.in_transaction
        assert programs(db).proposed == new
        record_workout(db, "w1", (NOW, NOW + timedelta(hours=1)), None, link)
        assert accept_proposal(db, new.id, NOW).status is ProgramStatus.ACTIVE

    def test_a_workout_outside_the_program_does_not_hold_it(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        accept_proposal(db, propose_program(db, proposal(ids, "Old"), NOW).id, NOW)
        record_workout(db, "w1", (NOW, None), None)
        new = propose_program(db, proposal(ids, "New"), NOW)

        assert accept_proposal(db, new.id, NOW).status is ProgramStatus.ACTIVE

    def test_accept_only_the_proposal(self, db: sqlite3.Connection, ids: dict[str, int]) -> None:
        active = accept_proposal(db, propose_program(db, proposal(ids), NOW).id, NOW)

        with pytest.raises(NoProposalError, match=rf"^program {active.id} is not the proposal$"):
            accept_proposal(db, active.id, NOW)

        assert not db.in_transaction


class Gym:
    """Trains the active program through the logging services."""

    def __init__(self, db: sqlite3.Connection, program: Program) -> None:
        """Train ``program`` from the day after ``NOW``."""
        self.db = db
        self.program = program
        self.ids = count(1)
        self.day = NOW

    def train(
        self,
        week: int,
        day: int,
        sets: dict[str, list[tuple[float | None, float | None]]],
        *,
        finish: bool = True,
    ) -> str:
        """Log a workout of program ``day`` (from 1) in ``week``: (amount, load) per set."""
        self.day += timedelta(days=1)
        client_id = f"00000000-0000-4000-8000-{next(self.ids):012d}"
        link = ProgramLink(self.program.days[day - 1].id, week)
        record_workout(self.db, client_id, (self.day, None), None, link)
        slots = {
            exercise.name.lower(): exercise
            for block in self.program.days[day - 1].blocks
            for exercise in block.exercises
        }
        for name, logged in sets.items():
            planned = slots[name]
            for amount, load in logged:
                timed = planned.measure is Measure.SECONDS
                reps, duration = (None, amount) if timed else (amount, None)
                values = SetValues(None if reps is None else int(reps), load, duration, None, None)
                placement = (client_id, planned.exercise_id)
                record_set(self.db, f"{client_id}-{next(self.ids)}", placement, values, planned.id)
        if finish:
            record_workout(self.db, client_id, (self.day, self.day), None, link)
        return client_id


@pytest.fixture
def gym(db: sqlite3.Connection, ids: dict[str, int]) -> Gym:
    program = accept_proposal(db, propose_program(db, proposal(ids), NOW).id, NOW)
    return Gym(db, program)


def planned(db: sqlite3.Connection) -> dict[str, PlannedExercise]:
    plan = today(db)
    assert plan is not None
    assert plan.day is not None
    return {
        exercise.name.lower(): exercise for block in plan.day.blocks for exercise in block.exercises
    }


class TestToday:
    def test_nothing_without_an_active_program(
        self, db: sqlite3.Connection, ids: dict[str, int]
    ) -> None:
        propose_program(db, proposal(ids), NOW)

        assert today(db) is None
        assert programs(db).next is None

    def test_a_new_program_starts_on_its_first_day(self, gym: Gym) -> None:
        plan = today(gym.db)

        assert plan is not None
        assert (plan.program_id, plan.program_name, plan.training_weeks, plan.days) == (
            gym.program.id,
            "Upper/Lower",
            6,
            2,
        )
        assert plan.workout_client_id is None
        assert plan.day is not None
        upper = gym.program.days[0]
        assert (plan.day.id, plan.day.position, plan.day.name) == (upper.id, 1, "Upper")
        assert (plan.day.week, plan.day.deload) == (1, False)
        assert [block.rest_s for block in plan.day.blocks] == [120, 60]
        bench = upper.blocks[0].exercises[0]
        assert plan.day.blocks[0].exercises == [
            PlannedExercise(
                bench.id,
                bench.exercise_id,
                "Bench",
                "barbell",
                Measure.REPS,
                0.0,
                3,
                8,
                10,
                "pause",
                Target(Decision.START, 60.0, (8, 8, 8)),
                None,
            )
        ]
        assert programs(gym.db).next == Position(1, 1)

    def test_the_days_follow_what_was_done(self, gym: Gym) -> None:
        gym.train(1, 1, {"bench": [(10, 60.0)] * 3})

        plan = today(gym.db)
        assert plan is not None
        assert plan.day is not None
        assert (plan.day.week, plan.day.name) == (1, "Lower")
        assert programs(gym.db).next == Position(1, 2)

        gym.train(1, 2, {})
        plan = today(gym.db)
        assert plan is not None
        assert plan.day is not None
        assert (plan.day.week, plan.day.name) == (2, "Upper")

    def test_targets_progress_from_the_last_session(self, gym: Gym) -> None:
        gym.train(1, 1, {"bench": [(10, 60.0)] * 3, "row": [(12, 40.0), (11, 40.0), (10, 40.0)]})
        gym.train(1, 2, {})

        exercises = planned(gym.db)

        assert exercises["bench"].target == Target(Decision.PROGRESS, 62.5, (8, 8, 8))
        assert exercises["row"].target == Target(Decision.REPEAT, 40.0, (12, 11, 10))
        assert exercises["curl"].target == Target(Decision.START, None, (10, 10, 10))

    def test_last_time_is_the_exercises_last_session(self, gym: Gym) -> None:
        gym.train(1, 1, {"bench": [(10, 60.0)]})

        last = planned(gym.db)["pull-up"].last
        assert last is None
        gym.train(1, 2, {"pull-up": [(7, None)]})

        last = planned(gym.db)["bench"].last
        assert last is not None
        assert last.sets == [SetView(1, 10, 60.0, None, None, None, last.sets[0].client_id)]

    def test_a_workout_in_progress_is_today(self, gym: Gym) -> None:
        gym.train(1, 1, {"bench": [(10, 60.0)] * 3})
        gym.train(1, 2, {"pull-up": [(8, None)] * 3})
        going = gym.train(2, 1, {"bench": [(4, 62.5)]}, finish=False)

        plan = today(gym.db)

        assert plan is not None
        assert plan.workout_client_id == going
        assert plan.day is not None
        assert (plan.day.week, plan.day.name) == (2, "Upper")
        bench = planned(gym.db)["bench"]
        # The unfinished session neither moves the target nor counts as last time.
        assert bench.target == Target(Decision.PROGRESS, 62.5, (8, 8, 8))
        assert bench.last is not None
        assert [logged.reps for logged in bench.last.sets] == [10, 10, 10]
        assert programs(gym.db).next == Position(2, 1)

    def test_a_workout_in_progress_on_another_day_is_today(self, gym: Gym) -> None:
        going = gym.train(1, 2, {}, finish=False)  # day 2 first, day 1 not done

        plan = today(gym.db)

        assert plan is not None
        assert plan.workout_client_id == going
        assert plan.day is not None
        assert (plan.day.week, plan.day.position, plan.day.name) == (1, 2, "Lower")
        assert programs(gym.db).next == Position(1, 2)

    def test_a_workout_of_a_replaced_program_changes_nothing(
        self, gym: Gym, ids: dict[str, int]
    ) -> None:
        # The app no longer lets this happen (see accepting below); older data might.
        gym.train(1, 1, {}, finish=False)
        gym.db.execute("UPDATE programs SET status = 'archived'")
        gym.db.commit()
        accept_proposal(gym.db, propose_program(gym.db, proposal(ids, "Next"), NOW).id, NOW)

        plan = today(gym.db)

        assert plan is not None
        assert (plan.program_name, plan.workout_client_id) == ("Next", None)
        assert plan.day is not None
        assert (plan.day.week, plan.day.position) == (1, 1)

    def test_a_workout_of_a_replaced_program_must_be_finished_first(
        self, gym: Gym, ids: dict[str, int]
    ) -> None:
        # A database from before accepting was refused mid-workout.
        old = gym.train(1, 1, {"bench": [(10, 60.0)]}, finish=False)
        gym.db.execute("UPDATE programs SET status = 'archived'")
        gym.db.commit()
        new = accept_proposal(gym.db, propose_program(gym.db, proposal(ids, "Next"), NOW).id, NOW)
        link = ProgramLink(new.days[0].id, 1)

        with pytest.raises(StaleProgramDayError):
            record_workout(gym.db, "w-new", (NOW, None), None, link)

        # The old one can still be finished, under its own program day.
        old_link = ProgramLink(gym.program.days[0].id, 1)
        finished = record_workout(gym.db, old, (NOW, NOW), None, old_link)
        assert finished.ended_at is not None
        record_workout(gym.db, "w-new", (NOW, None), None, link)

    def test_a_workout_outside_the_program_changes_nothing(self, gym: Gym) -> None:
        gym.train(1, 1, {})
        record_workout(gym.db, "ad-hoc", (NOW + timedelta(days=9), None), None)

        plan = today(gym.db)

        assert plan is not None
        assert plan.workout_client_id is None
        assert plan.day is not None
        assert plan.day.name == "Lower"

    def test_the_deload_week(self, gym: Gym) -> None:
        gym.train(6, 1, {"bench": [(9, 80.0)] * 3})
        gym.train(6, 2, {})

        plan = today(gym.db)

        assert plan is not None
        assert plan.day is not None
        assert (plan.day.week, plan.day.deload) == (7, True)
        assert planned(gym.db)["bench"].target == Target(Decision.DELOAD, 72.5, (8, 8))

    def test_after_the_deload_week_the_block_is_done(self, gym: Gym) -> None:
        gym.train(7, 2, {})

        plan = today(gym.db)

        assert plan is not None
        assert (plan.day, plan.workout_client_id, plan.days) == (None, None, 2)
        assert programs(gym.db).next is None

    def test_timed_exercises_count_seconds(self, gym: Gym) -> None:
        gym.train(1, 2, {"hang": [(45.0, None), (50.0, None)]})
        gym.train(2, 1, {})

        assert planned(gym.db)["hang"].target == Target(Decision.PROGRESS, 2.5, (30, 30))

    def test_a_set_without_its_amount_counts_none(self, gym: Gym) -> None:
        # A timed set logged with reps only has no seconds: it reached nothing.
        gym.train(1, 2, {"hang": [(None, 10.0), (None, 10.0)]})
        gym.train(2, 1, {})
        gym.db.execute("UPDATE workout_sets SET reps = 40")
        gym.db.execute("UPDATE block_exercises SET rep_min = 1")
        gym.db.commit()

        assert planned(gym.db)["hang"].target == Target(Decision.REDUCE, 7.5, (1, 1))

    def test_bodyweight_exercises_carry_body_weight(self, gym: Gym) -> None:
        save_profile(gym.db, Profile(70.0))
        gym.db.commit()
        gym.train(1, 1, {})

        assert planned(gym.db)["pull-up"].carried_kg == 65.1


def test_proposals_at_a_utc_time(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    program = propose_program(db, proposal(ids), datetime(2026, 1, 1, tzinfo=UTC))

    assert program.created_at == "2026-01-01T00:00:00+00:00"
