"""Logging use cases."""

import sqlite3
import threading
from contextlib import closing, suppress
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from trainer.domain.exercises import Equipment, Measure
from trainer.services.journal import (
    DuplicateExerciseError,
    InvalidWorkoutError,
    NewExercise,
    NotFoundError,
    add_exercise,
    record_set,
    record_workout,
    remove_set,
    remove_workout,
)
from trainer.storage import journal as journal_storage
from trainer.storage.catalogue import ExerciseSpec, add_alias, upsert_exercise
from trainer.storage.database import connect, migrate
from trainer.storage.journal import SetValues

W1 = "11111111-1111-4111-8111-111111111111"
START = datetime(2026, 9, 30, 9, 0, tzinfo=timezone(timedelta(hours=1)))
FIVE = SetValues(5, 60.0, None, None, None)

# Timestamps must not depend on the host's timezone (CI runs in UTC).
pytestmark = pytest.mark.usefixtures("far_east_timezone")


def bench(db: sqlite3.Connection) -> int:
    exercise_id = upsert_exercise(
        db,
        ExerciseSpec(
            "barbell bench press", "Barbell Bench Press", "barbell", "chest", Measure.REPS
        ),
    )
    db.commit()  # services open their own write transaction
    return exercise_id


class TestWorkouts:
    def test_record_workout_stores_utc_and_returns_the_detail(self, db: sqlite3.Connection) -> None:
        detail = record_workout(db, W1, (START, None), "push day")

        assert (detail.client_id, detail.started_at, detail.ended_at, detail.notes) == (
            W1,
            "2026-09-30T08:00:00+00:00",
            None,
            "push day",
        )
        assert not db.in_transaction

    def test_finishing_a_workout(self, db: sqlite3.Connection) -> None:
        record_workout(db, W1, (START, None), None)

        detail = record_workout(db, W1, (START, START + timedelta(hours=1)), None)

        assert detail.ended_at == "2026-09-30T09:00:00+00:00"

    def test_a_workout_may_end_when_it_starts(self, db: sqlite3.Connection) -> None:
        assert record_workout(db, W1, (START, START), None).ended_at == "2026-09-30T08:00:00+00:00"

    def test_a_workout_cannot_end_before_it_starts(self, db: sqlite3.Connection) -> None:
        with pytest.raises(InvalidWorkoutError, match=r"^a workout cannot end before it starts$"):
            record_workout(db, W1, (START, START - timedelta(seconds=1)), None)

        assert db.execute("SELECT count(*) FROM workouts").fetchone()[0] == 0

    def test_remove_workout(self, db: sqlite3.Connection) -> None:
        record_workout(db, W1, (START, None), None)

        remove_workout(db, W1)
        remove_workout(db, W1)

        assert db.execute("SELECT count(*) FROM workouts").fetchone()[0] == 0
        assert not db.in_transaction


class TestSets:
    def test_record_set_returns_the_whole_workout(self, db: sqlite3.Connection) -> None:
        exercise_id = bench(db)
        record_workout(db, W1, (START, None), None)

        detail = record_set(db, "s1", (W1, exercise_id), FIVE)
        detail = record_set(db, "s2", (W1, exercise_id), SetValues(3, 70.0, None, 9, None))

        assert [(block.name, len(block.sets)) for block in detail.exercises] == [
            ("Barbell Bench Press", 2)
        ]
        assert [(s.client_id, s.reps, s.load_kg, s.rpe) for s in detail.exercises[0].sets] == [
            ("s1", 5, 60.0, None),
            ("s2", 3, 70.0, 9),
        ]
        assert not db.in_transaction

    def test_unknown_workout(self, db: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError, match=r"^workout not found$"):
            record_set(db, "s1", (W1, bench(db)), FIVE)

    def test_unknown_exercise(self, db: sqlite3.Connection) -> None:
        record_workout(db, W1, (START, None), None)

        with pytest.raises(NotFoundError, match=r"^exercise not found$"):
            record_set(db, "s1", (W1, 999), FIVE)

    def test_remove_set(self, db: sqlite3.Connection) -> None:
        record_workout(db, W1, (START, None), None)
        record_set(db, "s1", (W1, bench(db)), FIVE)

        remove_set(db, "s1")
        remove_set(db, "s1")

        assert db.execute("SELECT count(*) FROM workout_sets").fetchone()[0] == 0
        assert not db.in_transaction


class TestExercises:
    def test_adds_a_new_exercise(self, db: sqlite3.Connection) -> None:
        bench(db)

        added = add_exercise(
            db,
            NewExercise("  Goblet   Squat ", Equipment.KETTLEBELL, "quads", Measure.REPS),
            allow_similar=False,
        )

        assert (
            added.name,
            added.equipment,
            added.muscle_groups,
            added.measure,
            added.workouts,
        ) == (
            "Goblet Squat",
            "kettlebell",
            "quads",
            Measure.REPS,
            0,
        )
        assert (
            db.execute("SELECT name FROM exercises WHERE id = ?", (added.id,)).fetchone()[0]
            == "goblet squat"
        )
        assert not db.in_transaction

    def test_a_timed_bodyweight_exercise(self, db: sqlite3.Connection) -> None:
        added = add_exercise(
            db,
            NewExercise("Plank", Equipment.BODYWEIGHT, None, Measure.SECONDS),
            allow_similar=False,
        )

        assert (added.equipment, added.measure) == ("bodyweight", Measure.SECONDS)

    @pytest.mark.parametrize("name", ["barbell BENCH press", "bench"])
    def test_a_taken_name_or_alias_is_refused_even_when_allowing_similar(
        self, db: sqlite3.Connection, name: str
    ) -> None:
        existing = bench(db)
        add_alias(db, "bench", existing)
        db.commit()

        with pytest.raises(DuplicateExerciseError) as caught:
            add_exercise(
                db, NewExercise(name, Equipment.BARBELL, None, Measure.REPS), allow_similar=True
            )

        assert caught.value.exact is True
        assert str(caught.value) == "exists"
        assert [match.id for match in caught.value.matches] == [existing]

    def test_a_similar_name_needs_confirmation(self, db: sqlite3.Connection) -> None:
        existing = bench(db)

        with pytest.raises(DuplicateExerciseError) as caught:
            add_exercise(
                db,
                NewExercise("Bench Press", Equipment.BARBELL, None, Measure.REPS),
                allow_similar=False,
            )

        assert caught.value.exact is False
        assert str(caught.value) == "similar"
        assert [match.name for match in caught.value.matches] == ["Barbell Bench Press"]
        assert caught.value.matches[0].id == existing

        added = add_exercise(
            db,
            NewExercise("Bench Press", Equipment.BARBELL, None, Measure.REPS),
            allow_similar=True,
        )
        assert added.name == "Bench Press"


def test_record_workout_accepts_utc_input(db: sqlite3.Connection) -> None:
    detail = record_workout(db, W1, (datetime(2026, 1, 1, tzinfo=UTC), None), None)

    assert detail.started_at == "2026-01-01T00:00:00+00:00"


class TestConcurrency:
    """Two request connections racing, synchronised right after slot allocation.

    Without the write lock both would read the same state: distinct sets would be
    given the same slot, and a replayed set would be inserted twice. With it the
    second writer queues, so the barrier times out for the first and is already
    broken for the second.
    """

    @pytest.fixture
    def database(self, tmp_path: Path) -> tuple[Path, int]:
        path = tmp_path / "trainer.db"
        with closing(connect(path)) as conn:
            migrate(conn)
            exercise_id = bench(conn)
            record_workout(conn, W1, (START, None), None)
        return path, exercise_id

    @pytest.fixture(autouse=True)
    def synchronise_allocation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        barrier = threading.Barrier(2)
        allocate = journal_storage._next_slot  # noqa: SLF001  # why: the race is inside it

        def synchronised(*args: Any) -> tuple[int, int]:  # noqa: ANN401  # why: passthrough
            slot = allocate(*args)
            with suppress(threading.BrokenBarrierError):
                barrier.wait(timeout=0.5)
            return slot

        monkeypatch.setattr(journal_storage, "_next_slot", synchronised)

    @staticmethod
    def race(database: tuple[Path, int], client_ids: tuple[str, str]) -> list[BaseException]:
        path, exercise_id = database
        errors: list[BaseException] = []

        def log(client_id: str) -> None:
            with closing(connect(path)) as conn:
                try:
                    record_set(conn, client_id, (W1, exercise_id), FIVE)
                except Exception as error:  # noqa: BLE001  # why: collected and asserted on
                    errors.append(error)

        threads = [threading.Thread(target=log, args=(client_id,)) for client_id in client_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return errors

    def test_distinct_sets_get_distinct_slots(self, database: tuple[Path, int]) -> None:
        assert self.race(database, ("s1", "s2")) == []

        with closing(connect(database[0])) as conn:
            slots = conn.execute(
                "SELECT exercise_position, set_number FROM workout_sets ORDER BY set_number"
            ).fetchall()
        assert [tuple(slot) for slot in slots] == [(1, 1), (1, 2)]

    def test_a_replayed_set_is_written_once(self, database: tuple[Path, int]) -> None:
        assert self.race(database, ("s1", "s1")) == []

        with closing(connect(database[0])) as conn:
            count = conn.execute("SELECT count(*) FROM workout_sets").fetchone()[0]
        assert count == 1
