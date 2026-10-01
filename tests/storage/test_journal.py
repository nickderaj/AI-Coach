"""App writes keyed by client ids."""

import sqlite3

import pytest

from trainer.domain.exercises import Measure
from trainer.storage.catalogue import (
    ExerciseSpec,
    add_alias,
    create_exercise,
    known_names,
    upsert_exercise,
)
from trainer.storage.history import current_workout
from trainer.storage.journal import (
    JournalConflictError,
    ProgramLink,
    SetValues,
    delete_set,
    delete_workout,
    save_set,
    save_workout,
    workout_id_for,
)

W1 = "11111111-1111-4111-8111-111111111111"
W2 = "22222222-2222-4222-8222-222222222222"
FIVE = SetValues(5, 60.0, None, None, None)


def exercise(db: sqlite3.Connection, name: str) -> int:
    return upsert_exercise(db, ExerciseSpec(name, name.title(), None, None, Measure.REPS))


def slots(db: sqlite3.Connection, workout_id: int) -> list[tuple[str, int, int]]:
    return [
        (row[0], row[1], row[2])
        for row in db.execute(
            "SELECT client_id, exercise_position, set_number FROM workout_sets "
            "WHERE workout_id = ? ORDER BY id",
            (workout_id,),
        )
    ]


class TestWorkouts:
    def test_save_creates_an_app_workout(self, db: sqlite3.Connection) -> None:
        workout_id = save_workout(db, W1, ("2026-09-30T08:00:00+00:00", None), "legs")

        assert tuple(
            db.execute(
                "SELECT started_at, ended_at, notes, source, client_id FROM workouts WHERE id = ?",
                (workout_id,),
            ).fetchone()
        ) == ("2026-09-30T08:00:00+00:00", None, "legs", "app", W1)
        assert workout_id_for(db, W1) == workout_id

    def test_save_again_updates_in_place(self, db: sqlite3.Connection) -> None:
        first = save_workout(db, W1, ("2026-09-30T08:00:00+00:00", None), None)

        second = save_workout(
            db, W1, ("2026-09-30T08:05:00+00:00", "2026-09-30T09:00:00+00:00"), "done"
        )

        assert second == first
        assert tuple(db.execute("SELECT started_at, ended_at, notes FROM workouts").fetchone()) == (
            "2026-09-30T08:05:00+00:00",
            "2026-09-30T09:00:00+00:00",
            "done",
        )

    def test_unknown_client_id(self, db: sqlite3.Connection) -> None:
        assert workout_id_for(db, W2) is None

    def test_delete_workout_cascades_and_is_idempotent(self, db: sqlite3.Connection) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        save_set(db, "s1", (workout_id, exercise(db, "squat"), None), FIVE)

        assert delete_workout(db, W1) is True
        assert delete_workout(db, W1) is False
        assert db.execute("SELECT count(*) FROM workout_sets").fetchone()[0] == 0

    def test_imported_workouts_are_not_touched_by_client_ids(self, db: sqlite3.Connection) -> None:
        db.execute("INSERT INTO workouts (started_at, source) VALUES ('t', 'v1')")

        assert delete_workout(db, W1) is False
        assert db.execute("SELECT count(*) FROM workouts").fetchone()[0] == 1


class TestSets:
    def test_sets_continue_the_current_block_and_start_new_ones(
        self, db: sqlite3.Connection
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        squat, row = exercise(db, "squat"), exercise(db, "row")

        for client_id, exercise_id in [
            ("a", squat),
            ("b", squat),
            ("c", row),
            ("d", squat),
            ("e", squat),
        ]:
            save_set(db, client_id, (workout_id, exercise_id, None), FIVE)

        assert slots(db, workout_id) == [
            ("a", 1, 1),
            ("b", 1, 2),
            ("c", 2, 1),
            ("d", 3, 1),
            ("e", 3, 2),
        ]

    def test_saving_again_updates_values_without_moving_the_set(
        self, db: sqlite3.Connection
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        squat = exercise(db, "squat")
        first = save_set(db, "a", (workout_id, squat, None), FIVE)
        save_set(db, "b", (workout_id, squat, None), FIVE)

        again = save_set(db, "a", (workout_id, squat, None), SetValues(3, 70.5, 12.0, 9, "heavy"))

        assert again == first
        assert slots(db, workout_id) == [("a", 1, 1), ("b", 1, 2)]
        assert tuple(
            db.execute(
                "SELECT reps, load_kg, duration_s, rpe, notes FROM workout_sets WHERE id = ?",
                (first,),
            ).fetchone()
        ) == (3, 70.5, 12.0, 9, "heavy")

    @pytest.mark.parametrize("move", ["workout", "exercise"])
    def test_a_client_id_cannot_move_to_another_workout_or_exercise(
        self, db: sqlite3.Connection, move: str
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        other_workout = save_workout(db, W2, ("t", None), None)
        squat, row = exercise(db, "squat"), exercise(db, "row")
        save_set(db, "a", (workout_id, squat, None), FIVE)
        placement = (other_workout, squat, None) if move == "workout" else (workout_id, row, None)

        with pytest.raises(
            JournalConflictError, match=r"^set a belongs to another workout or exercise$"
        ):
            save_set(db, "a", placement, FIVE)

    def test_delete_set_is_idempotent(self, db: sqlite3.Connection) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        save_set(db, "a", (workout_id, exercise(db, "squat"), None), FIVE)

        assert delete_set(db, "a") is True
        assert delete_set(db, "a") is False


class TestCurrentWorkout:
    def test_none_without_app_workouts(self, db: sqlite3.Connection) -> None:
        db.execute("INSERT INTO workouts (started_at, source) VALUES ('2026-09-30T00:00', 'v1')")

        assert current_workout(db) is None

    def test_latest_unfinished_app_workout(self, db: sqlite3.Connection) -> None:
        save_workout(db, W1, ("2026-09-29T08:00:00+00:00", None), None)
        save_workout(db, W2, ("2026-09-30T08:00:00+00:00", "2026-09-30T09:00:00+00:00"), None)
        latest_unfinished = save_workout(
            db, "33333333-3333-4333-8333-333333333333", ("2026-09-30T07:00:00+00:00", None), None
        )

        found = current_workout(db)

        assert found is not None
        assert (found.id, found.client_id) == (
            latest_unfinished,
            "33333333-3333-4333-8333-333333333333",
        )

    def test_ties_go_to_the_newest_id(self, db: sqlite3.Connection) -> None:
        save_workout(db, W1, ("2026-09-30T08:00:00+00:00", None), None)
        newest = save_workout(db, W2, ("2026-09-30T08:00:00+00:00", None), None)

        found = current_workout(db)

        assert found is not None
        assert found.id == newest


class TestCatalogueWrites:
    def test_create_exercise_refuses_a_taken_name(self, db: sqlite3.Connection) -> None:
        spec = ExerciseSpec("Goblet  Squat", "Goblet Squat", "dumbbell", "legs", Measure.REPS)

        first = create_exercise(db, spec)

        assert first > 0
        with pytest.raises(sqlite3.IntegrityError):
            create_exercise(db, spec)
        assert tuple(
            db.execute(
                "SELECT name, display_name, equipment, muscle_groups, measure FROM exercises"
            ).fetchone()
        ) == ("goblet squat", "Goblet Squat", "dumbbell", "legs", "reps")

    def test_known_names_include_aliases_in_id_order(self, db: sqlite3.Connection) -> None:
        row = exercise(db, "row")
        bench = exercise(db, "bench press")
        add_alias(db, "bench", bench)

        assert known_names(db) == [(row, "Row"), (bench, "Bench Press"), (bench, "bench")]


class TestProgramSets:
    """Sets for program exercises keep one position per exercise, supersets included."""

    @pytest.fixture
    def slots_of(self, db: sqlite3.Connection) -> dict[str, tuple[int, int]]:
        """Three program exercises: (exercise id, block exercise id) by name."""
        db.executescript(
            """
            INSERT INTO programs (id, name, training_weeks, status, created_at)
                VALUES (1, 'P', 6, 'active', 't');
            INSERT INTO program_days (id, program_id, position, name) VALUES (1, 1, 1, 'Day');
            INSERT INTO program_blocks (id, day_id, position, rest_s)
                VALUES (1, 1, 1, 90), (2, 1, 2, 60);
            """
        )
        found: dict[str, tuple[int, int]] = {}
        for slot_id, block, name in [(11, 1, "squat"), (21, 2, "row"), (22, 2, "curl")]:
            exercise_id = exercise(db, name)
            db.execute(
                "INSERT INTO block_exercises (id, block_id, position, exercise_id, sets, "
                "rep_min, rep_max) VALUES (?, ?, ?, ?, 3, 8, 10)",
                (slot_id, block, slot_id % 10, exercise_id),
            )
            found[name] = (exercise_id, slot_id)
        return found

    def test_a_superset_alternates_without_splitting(
        self, db: sqlite3.Connection, slots_of: dict[str, tuple[int, int]]
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None, ProgramLink(1, 1))

        for client_id, name in [
            ("a", "squat"),
            ("b", "squat"),
            ("c", "row"),
            ("d", "curl"),
            ("e", "row"),
            ("f", "curl"),
        ]:
            exercise_id, slot = slots_of[name]
            save_set(db, client_id, (workout_id, exercise_id, slot), FIVE)

        assert slots(db, workout_id) == [
            ("a", 1, 1),
            ("b", 1, 2),
            ("c", 2, 1),
            ("d", 3, 1),
            ("e", 2, 2),
            ("f", 3, 2),
        ]
        assert [
            row[0] for row in db.execute("SELECT block_exercise_id FROM workout_sets ORDER BY id")
        ] == [11, 11, 21, 22, 21, 22]

    def test_an_extra_set_of_the_same_exercise_starts_its_own_block(
        self, db: sqlite3.Connection, slots_of: dict[str, tuple[int, int]]
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        squat, slot = slots_of["squat"]
        save_set(db, "a", (workout_id, squat, slot), FIVE)

        save_set(db, "b", (workout_id, squat, None), FIVE)
        save_set(db, "c", (workout_id, squat, None), FIVE)
        save_set(db, "d", (workout_id, squat, slot), FIVE)

        assert slots(db, workout_id) == [("a", 1, 1), ("b", 2, 1), ("c", 2, 2), ("d", 1, 2)]

    def test_a_program_set_after_an_extra_one_starts_its_own_block(
        self, db: sqlite3.Connection, slots_of: dict[str, tuple[int, int]]
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        squat, slot = slots_of["squat"]
        save_set(db, "a", (workout_id, squat, None), FIVE)

        save_set(db, "b", (workout_id, squat, slot), FIVE)

        assert slots(db, workout_id) == [("a", 1, 1), ("b", 2, 1)]

    def test_a_client_id_cannot_move_to_another_program_exercise(
        self, db: sqlite3.Connection, slots_of: dict[str, tuple[int, int]]
    ) -> None:
        workout_id = save_workout(db, W1, ("t", None), None)
        squat, slot = slots_of["squat"]
        save_set(db, "a", (workout_id, squat, slot), FIVE)

        for moved in (None, 21):
            with pytest.raises(JournalConflictError):
                save_set(db, "a", (workout_id, squat, moved), FIVE)

    def test_a_workout_records_and_replaces_its_program_day(
        self, db: sqlite3.Connection, slots_of: dict[str, tuple[int, int]]
    ) -> None:
        assert slots_of
        workout_id = save_workout(db, W1, ("t", None), None, ProgramLink(1, 3))

        def link() -> tuple[int | None, int | None]:
            row = db.execute(
                "SELECT program_day_id, program_week FROM workouts WHERE id = ?", (workout_id,)
            ).fetchone()
            return row[0], row[1]

        assert link() == (1, 3)
        save_workout(db, W1, ("t", "u"), None, ProgramLink(1, 4))
        assert link() == (1, 4)
        save_workout(db, W1, ("t", "u"), None)
        assert link() == (None, None)
