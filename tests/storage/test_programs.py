"""Programs in SQLite: saving, reading, activating, and where training has got to."""

import sqlite3

import pytest

from trainer.domain.exercises import Measure
from trainer.domain.programs import Position
from trainer.storage.catalogue import ExerciseSpec, upsert_exercise
from trainer.storage.journal import ProgramLink, SetValues, save_set, save_workout
from trainer.storage.programs import (
    BlockSpec,
    DayProgram,
    DaySpec,
    Program,
    ProgramBlock,
    ProgramDay,
    ProgramExercise,
    ProgramNotFoundError,
    ProgramSpec,
    ProgramStatus,
    SlotPlace,
    SlotSet,
    SlotSpec,
    activate_program,
    archive_program,
    day_claimed,
    day_program,
    get_program,
    insert_program,
    last_position,
    last_slot_sets,
    program_with_status,
    slot_place,
)


def exercise(db: sqlite3.Connection, name: str, equipment: str, measure: Measure) -> int:
    return upsert_exercise(db, ExerciseSpec(name, name.title(), equipment, None, measure))


@pytest.fixture
def ids(db: sqlite3.Connection) -> dict[str, int]:
    return {
        "bench": exercise(db, "bench", "barbell", Measure.REPS),
        "row": exercise(db, "row", "cable", Measure.REPS),
        "hang": exercise(db, "dead hang", "bodyweight", Measure.SECONDS),
        "band": exercise(db, "pull apart", "band", Measure.REPS),
    }


def spec(ids: dict[str, int], name: str = "Upper/Lower") -> ProgramSpec:
    return ProgramSpec(
        name,
        "two days",
        6,
        (
            DaySpec(
                "Upper",
                (
                    BlockSpec(120, (SlotSpec(ids["bench"], 3, 8, 10, 60.0, "pause"),)),
                    BlockSpec(
                        60,
                        (
                            SlotSpec(ids["row"], 3, 10, 12, None, None),
                            SlotSpec(ids["band"], 2, 15, 20, None, None),
                        ),
                    ),
                ),
            ),
            DaySpec("Grip", (BlockSpec(90, (SlotSpec(ids["hang"], 2, 30, 45, None, None),)),)),
        ),
    )


def test_a_program_round_trips(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    db.execute("UPDATE exercises SET load_increment_kg = 1.0 WHERE id = ?", (ids["row"],))

    program_id = insert_program(db, spec(ids), ProgramStatus.PROPOSED, "2026-10-01T08:00:00+00:00")

    days = [tuple(row) for row in db.execute("SELECT id FROM program_days ORDER BY position")]
    slots = [
        row[0]
        for row in db.execute(
            "SELECT x.id FROM block_exercises x JOIN program_blocks b ON b.id = x.block_id "
            "JOIN program_days d ON d.id = b.day_id ORDER BY d.position, b.position, x.position"
        )
    ]
    assert get_program(db, program_id) == Program(
        program_id,
        "Upper/Lower",
        "two days",
        6,
        ProgramStatus.PROPOSED,
        "2026-10-01T08:00:00+00:00",
        None,
        [
            ProgramDay(
                days[0][0],
                "Upper",
                [
                    ProgramBlock(
                        120,
                        [
                            ProgramExercise(
                                slots[0],
                                ids["bench"],
                                "Bench",
                                "barbell",
                                Measure.REPS,
                                3,
                                8,
                                10,
                                60.0,
                                "pause",
                                2.5,
                            )
                        ],
                    ),
                    ProgramBlock(
                        60,
                        [
                            ProgramExercise(
                                slots[1],
                                ids["row"],
                                "Row",
                                "cable",
                                Measure.REPS,
                                3,
                                10,
                                12,
                                None,
                                None,
                                1.0,  # its own step wins over the cable's
                            ),
                            ProgramExercise(
                                slots[2],
                                ids["band"],
                                "Pull Apart",
                                "band",
                                Measure.REPS,
                                2,
                                15,
                                20,
                                None,
                                None,
                                None,
                            ),
                        ],
                    ),
                ],
            ),
            ProgramDay(
                days[1][0],
                "Grip",
                [
                    ProgramBlock(
                        90,
                        [
                            ProgramExercise(
                                slots[3],
                                ids["hang"],
                                "Dead Hang",
                                "bodyweight",
                                Measure.SECONDS,
                                2,
                                30,
                                45,
                                None,
                                None,
                                2.5,
                            )
                        ],
                    )
                ],
            ),
        ],
    )


def test_positions_count_from_one(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    insert_program(db, spec(ids), ProgramStatus.PROPOSED, "t")

    def positions(table: str) -> list[int]:
        return [row[0] for row in db.execute(f"SELECT position FROM {table} ORDER BY id")]  # noqa: S608  # why: table names are the literals below

    assert positions("program_days") == [1, 2]
    assert positions("program_blocks") == [1, 2, 1]
    assert positions("block_exercises") == [1, 1, 2, 1]


def test_days_and_blocks_alike_stay_apart(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    # Two days of the same name, each with two blocks of the same rest, in order.
    block = BlockSpec(90, (SlotSpec(ids["bench"], 3, 8, 10, None, None),))
    other = BlockSpec(90, (SlotSpec(ids["row"], 3, 8, 10, None, None),))
    same = ProgramSpec("Full", None, 6, (DaySpec("Full", (block, other)),) * 2)

    program = get_program(db, insert_program(db, same, ProgramStatus.ACTIVE, "t"))

    assert [[len(b.exercises) for b in day.blocks] for day in program.days] == [[1, 1], [1, 1]]
    assert [b.exercises[0].name for b in program.days[1].blocks] == ["Bench", "Row"]


def test_programs_are_kept_apart(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    first = insert_program(db, spec(ids, "First"), ProgramStatus.ACTIVE, "t")
    second = insert_program(db, spec(ids, "Second"), ProgramStatus.PROPOSED, "t")

    assert [day.name for day in get_program(db, first).days] == ["Upper", "Grip"]
    assert get_program(db, second).name == "Second"
    assert program_with_status(db, ProgramStatus.ACTIVE) == first
    assert program_with_status(db, ProgramStatus.PROPOSED) == second
    assert program_with_status(db, ProgramStatus.ARCHIVED) is None


def test_an_unknown_program(db: sqlite3.Connection) -> None:
    with pytest.raises(ProgramNotFoundError, match=r"^no program 7$"):
        get_program(db, 7)


def test_archive_program_keeps_it_and_its_days(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    kept = insert_program(db, spec(ids, "Kept"), ProgramStatus.ACTIVE, "t")
    gone = insert_program(db, spec(ids, "Gone"), ProgramStatus.PROPOSED, "t")

    archive_program(db, gone)

    assert program_with_status(db, ProgramStatus.PROPOSED) is None
    assert get_program(db, gone).status is ProgramStatus.ARCHIVED
    assert get_program(db, kept).status is ProgramStatus.ACTIVE
    assert len(get_program(db, gone).days) == 2


def test_activate_archives_the_active_program(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    old = insert_program(db, spec(ids, "Old"), ProgramStatus.ACTIVE, "t")
    new = insert_program(db, spec(ids, "New"), ProgramStatus.PROPOSED, "t")

    activate_program(db, new, "2026-10-02T07:00:00+00:00")

    assert get_program(db, old).status is ProgramStatus.ARCHIVED
    assert get_program(db, old).started_at is None
    activated = get_program(db, new)
    assert (activated.status, activated.started_at) == (
        ProgramStatus.ACTIVE,
        "2026-10-02T07:00:00+00:00",
    )


def test_activate_without_an_active_program(db: sqlite3.Connection, ids: dict[str, int]) -> None:
    new = insert_program(db, spec(ids), ProgramStatus.PROPOSED, "t")

    activate_program(db, new, "s")

    assert program_with_status(db, ProgramStatus.ACTIVE) == new


class Trained:
    """A database with the program active, and helpers to train it."""

    def __init__(self, db: sqlite3.Connection, ids: dict[str, int]) -> None:
        """Save the program as the active one."""
        self.db = db
        self.ids = ids
        self.program = get_program(db, insert_program(db, spec(ids), ProgramStatus.ACTIVE, "t"))
        self.count = 0

    def slot(self, day: int, block: int = 0, position: int = 0) -> ProgramExercise:
        return self.program.days[day].blocks[block].exercises[position]

    def workout(self, started_at: str, link: tuple[int, int] | None, *, finished: bool) -> int:
        self.count += 1
        ended = started_at if finished else None
        program = None if link is None else ProgramLink(self.program.days[link[1]].id, link[0])
        return save_workout(self.db, f"w{self.count}", (started_at, ended), None, program)

    def log(self, workout_id: int, slot: ProgramExercise, *sets: tuple[int, float]) -> None:
        for reps, load in sets:
            self.count += 1
            values = SetValues(reps, load, None, None, None)
            save_set(self.db, f"s{self.count}", (workout_id, slot.exercise_id, slot.id), values)


@pytest.fixture
def trained(db: sqlite3.Connection, ids: dict[str, int]) -> Trained:
    return Trained(db, ids)


class TestLastPosition:
    def test_nothing_done_yet(self, trained: Trained) -> None:
        assert last_position(trained.db, trained.program.id) is None

    def test_the_latest_finished_workout(self, trained: Trained) -> None:
        trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=True)
        trained.workout("2026-10-03T08:00:00+00:00", (1, 1), finished=True)
        trained.workout("2026-10-02T08:00:00+00:00", (2, 0), finished=True)  # logged late

        assert last_position(trained.db, trained.program.id) == Position(1, 2)

    def test_the_later_id_breaks_a_tie(self, trained: Trained) -> None:
        trained.workout("2026-10-01T08:00:00+00:00", (1, 1), finished=True)
        trained.workout("2026-10-01T08:00:00+00:00", (2, 0), finished=True)

        assert last_position(trained.db, trained.program.id) == Position(2, 1)

    def test_unfinished_and_unlinked_workouts_do_not_count(self, trained: Trained) -> None:
        trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=True)
        trained.workout("2026-10-02T08:00:00+00:00", (1, 1), finished=False)
        trained.workout("2026-10-03T08:00:00+00:00", None, finished=True)

        assert last_position(trained.db, trained.program.id) == Position(1, 1)

    def test_another_programs_workouts_do_not_count(self, trained: Trained) -> None:
        trained.workout("2026-10-01T08:00:00+00:00", (3, 1), finished=True)

        assert last_position(trained.db, trained.program.id + 1) is None


class TestLastSlotSets:
    def test_none_yet(self, trained: Trained) -> None:
        assert last_slot_sets(trained.db, trained.slot(0).id, 6) == []

    def test_the_latest_finished_session_in_order(self, trained: Trained) -> None:
        bench = trained.slot(0)
        older = trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=True)
        trained.log(older, bench, (10, 60.0), (10, 60.0))
        newer = trained.workout("2026-10-08T08:00:00+00:00", (2, 0), finished=True)
        trained.log(newer, bench, (9, 62.5), (8, 62.5), (7, 62.5))

        assert last_slot_sets(trained.db, bench.id, 6) == [
            SlotSet(9, 62.5, None),
            SlotSet(8, 62.5, None),
            SlotSet(7, 62.5, None),
        ]

    def test_the_later_id_breaks_a_tie(self, trained: Trained) -> None:
        bench = trained.slot(0)
        first = trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=True)
        trained.log(first, bench, (10, 60.0))
        second = trained.workout("2026-10-01T08:00:00+00:00", (2, 0), finished=True)
        trained.log(second, bench, (8, 62.5))

        assert last_slot_sets(trained.db, bench.id, 6) == [SlotSet(8, 62.5, None)]

    def test_only_this_program_exercises_sets(self, trained: Trained) -> None:
        row, band = trained.slot(0, 1, 0), trained.slot(0, 1, 1)
        workout = trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=True)
        trained.log(workout, row, (12, 40.0))
        trained.log(workout, band, (20, 0.0))
        trained.log(workout, row, (11, 40.0))

        assert last_slot_sets(trained.db, row.id, 6) == [
            SlotSet(12, 40.0, None),
            SlotSet(11, 40.0, None),
        ]

    def test_unfinished_workouts_do_not_count(self, trained: Trained) -> None:
        bench = trained.slot(0)
        done = trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=True)
        trained.log(done, bench, (10, 60.0))
        going = trained.workout("2026-10-08T08:00:00+00:00", (2, 0), finished=False)
        trained.log(going, bench, (3, 62.5))

        assert last_slot_sets(trained.db, bench.id, 6) == [SlotSet(10, 60.0, None)]

    def test_weeks_after_the_limit_do_not_count(self, trained: Trained) -> None:
        bench = trained.slot(0)
        training = trained.workout("2026-10-01T08:00:00+00:00", (6, 0), finished=True)
        trained.log(training, bench, (10, 60.0))
        deload = trained.workout("2026-10-08T08:00:00+00:00", (7, 0), finished=True)
        trained.log(deload, bench, (8, 52.5))

        assert last_slot_sets(trained.db, bench.id, 6) == [SlotSet(10, 60.0, None)]
        assert last_slot_sets(trained.db, bench.id, 7) == [SlotSet(8, 52.5, None)]


def test_slot_place(trained: Trained) -> None:
    band = trained.slot(0, 1, 1)

    assert slot_place(trained.db, band.id) == SlotPlace(
        trained.program.days[0].id, band.exercise_id
    )
    assert slot_place(trained.db, 999) is None


def test_day_program_counts_the_deload_week(trained: Trained) -> None:
    day = trained.program.days[1].id

    assert day_program(trained.db, day) == DayProgram(7, active=True)
    trained.db.execute("UPDATE programs SET status = 'archived'")
    assert day_program(trained.db, day) == DayProgram(7, active=False)
    assert day_program(trained.db, 999) is None


def test_day_claimed_by_any_workout_of_that_week(trained: Trained) -> None:
    day = trained.program.days[0].id
    trained.workout("2026-10-01T08:00:00+00:00", (1, 0), finished=False)
    trained.workout("2026-10-02T08:00:00+00:00", (2, 0), finished=True)

    assert day_claimed(trained.db, day, 1) is True  # in progress
    assert day_claimed(trained.db, day, 2) is True  # done
    assert day_claimed(trained.db, day, 3) is False
    assert day_claimed(trained.db, trained.program.days[1].id, 2) is False
