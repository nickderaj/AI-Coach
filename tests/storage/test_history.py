"""History read models, over the imported v1 fixture."""

import sqlite3

import pytest

from trainer.domain.exercises import Measure
from trainer.storage.catalogue import ExerciseSpec, upsert_exercise
from trainer.storage.history import (
    ExerciseBlock,
    ExerciseLine,
    ExerciseSession,
    ExerciseSummary,
    SetView,
    WorkoutNotFoundError,
    WorkoutSummary,
    exercise_history,
    get_workout,
    list_exercises,
    list_workouts,
)

AUGUST = "2026-08-17T11:36:06+00:00"
JULY = "2026-07-09T10:47:23+00:00"


def ids(db: sqlite3.Connection) -> dict[str, int]:
    return {row[0]: row[1] for row in db.execute("SELECT name, id FROM exercises")}


def set_view(number: int, reps: int | None = None, load: float | None = None) -> SetView:
    return SetView(number, reps, load, None, None, None, None)


def test_list_workouts_newest_first(imported: sqlite3.Connection) -> None:
    july, august = (row[0] for row in imported.execute("SELECT id FROM workouts ORDER BY id"))

    assert list_workouts(imported, 10) == [
        WorkoutSummary(
            august,
            AUGUST,
            "2026-08-17T12:09:54+00:00",
            [
                ExerciseLine(1, "Lat Pulldown", Measure.REPS, 1, set_view(1, 12, 50.0)),
                ExerciseLine(2, "Pull-up", Measure.REPS, 1, set_view(1, 8)),
            ],
            2,
            600.0,
        ),
        WorkoutSummary(
            july,
            JULY,
            None,
            [
                # the heaviest set is the best, even with fewer reps
                ExerciseLine(
                    1,
                    "Barbell Bench Press",
                    Measure.REPS,
                    2,
                    SetView(2, 6, 70.0, None, 8, "grindy", None),
                ),
                ExerciseLine(
                    2,
                    "Dead Hang",
                    Measure.SECONDS,
                    1,
                    SetView(1, None, None, 50.0, None, None, None),
                ),
            ],
            3,
            900.0,  # 8 x 60 + 6 x 70; bodyweight and timed sets add nothing
        ),
    ]


def test_list_workouts_respects_the_limit(imported: sqlite3.Connection) -> None:
    assert [workout.started_at for workout in list_workouts(imported, 1)] == [AUGUST]


def test_list_workouts_breaks_ties_by_newest_id(db: sqlite3.Connection) -> None:
    for _ in range(2):
        db.execute(
            "INSERT INTO workouts (started_at, source) VALUES ('2026-01-01T00:00:00+00:00', 't')"
        )

    assert [workout.id for workout in list_workouts(db, 10)] == [2, 1]


def test_get_workout_groups_sets_by_exercise(imported: sqlite3.Connection) -> None:
    july = imported.execute("SELECT id FROM workouts WHERE started_at = ?", (JULY,)).fetchone()[0]
    exercise = ids(imported)

    detail = get_workout(imported, july)

    assert detail is not None
    assert (detail.id, detail.started_at, detail.ended_at, detail.notes) == (
        july,
        JULY,
        None,
        "first",
    )
    assert detail.exercises == [
        ExerciseBlock(
            1,
            exercise["barbell bench press"],
            "Barbell Bench Press",
            Measure.REPS,
            [set_view(1, 8, 60.0), SetView(2, 6, 70.0, None, 8, "grindy", None)],
        ),
        ExerciseBlock(
            2,
            exercise["dead hang"],
            "Dead Hang",
            Measure.SECONDS,
            [SetView(1, None, None, 50.0, None, None, None)],
        ),
    ]


def test_get_workout_carries_end_time_and_notes(imported: sqlite3.Connection) -> None:
    august = imported.execute("SELECT id FROM workouts WHERE started_at = ?", (AUGUST,)).fetchone()

    detail = get_workout(imported, august[0])

    assert detail is not None
    assert (detail.ended_at, detail.notes) == ("2026-08-17T12:09:54+00:00", "good")
    assert [(block.position, block.name) for block in detail.exercises] == [
        (1, "Lat Pulldown"),
        (2, "Pull-up"),
    ]


def test_get_workout_missing(imported: sqlite3.Connection) -> None:
    with pytest.raises(WorkoutNotFoundError, match=r"^no workout 999$"):
        get_workout(imported, 999)


def test_list_exercises_recent_first_then_untrained_by_name(imported: sqlite3.Connection) -> None:
    upsert_exercise(
        imported, ExerciseSpec("zercher squat", "Zercher Squat", None, None, Measure.REPS)
    )
    upsert_exercise(
        imported, ExerciseSpec("arnold press", "Arnold Press", None, None, Measure.REPS)
    )
    exercise = ids(imported)

    assert list_exercises(imported) == [
        ExerciseSummary(
            exercise["lat pulldown"],
            "Lat Pulldown",
            "cable",
            "back,biceps",
            Measure.REPS,
            1,
            AUGUST,
            50.0,
        ),
        ExerciseSummary(
            exercise["pullup"],
            "Pull-up",
            "bodyweight",
            "back,biceps",
            Measure.REPS,
            1,
            AUGUST,
            None,
        ),
        ExerciseSummary(
            exercise["barbell bench press"],
            "Barbell Bench Press",
            "barbell",
            "chest,triceps",
            Measure.REPS,
            1,
            JULY,
            70.0,
        ),
        ExerciseSummary(
            exercise["dead hang"], "Dead Hang", "bodyweight", "grip", Measure.SECONDS, 1, JULY, None
        ),
        ExerciseSummary(
            exercise["arnold press"], "Arnold Press", None, None, Measure.REPS, 0, None, None
        ),
        ExerciseSummary(
            exercise["zercher squat"], "Zercher Squat", None, None, Measure.REPS, 0, None, None
        ),
    ]


def test_exercise_history_newest_session_first(imported: sqlite3.Connection) -> None:
    bench = ids(imported)["barbell bench press"]
    later = imported.execute(
        "INSERT INTO workouts (started_at, source) "
        "VALUES ('2026-09-01T10:00:00+00:00', 't') RETURNING id"
    ).fetchone()[0]
    imported.execute(
        "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, "
        "reps, load_kg) VALUES (?, ?, 1, 1, 5, 80.0)",
        (later, bench),
    )
    july = imported.execute("SELECT id FROM workouts WHERE started_at = ?", (JULY,)).fetchone()[0]

    history = exercise_history(imported, bench)

    assert history is not None
    assert history.exercise.workouts == 2
    assert history.exercise.best_load_kg == 80.0
    assert history.sessions == [
        ExerciseSession(later, 1, "2026-09-01T10:00:00+00:00", [set_view(1, 5, 80.0)]),
        ExerciseSession(
            july, 1, JULY, [set_view(1, 8, 60.0), SetView(2, 6, 70.0, None, 8, "grindy", None)]
        ),
    ]


def test_exercise_history_of_an_untrained_exercise(db: sqlite3.Connection) -> None:
    exercise_id = upsert_exercise(db, ExerciseSpec("x", "X", None, None, Measure.REPS))

    history = exercise_history(db, exercise_id)

    assert history is not None
    assert history.sessions == []
    assert history.exercise.workouts == 0


def test_exercise_history_missing(db: sqlite3.Connection) -> None:
    assert exercise_history(db, 999) is None


def add_set(db: sqlite3.Connection, workout_id: int, exercise_id: int, position: int) -> None:
    db.execute(
        "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, reps) "
        "VALUES (?, ?, ?, 1, 5)",
        (workout_id, exercise_id, position),
    )


def test_an_exercise_repeated_later_in_a_workout_stays_a_separate_block(
    db: sqlite3.Connection,
) -> None:
    bench = upsert_exercise(db, ExerciseSpec("bench", "Bench", None, None, Measure.REPS))
    row = upsert_exercise(db, ExerciseSpec("row", "Row", None, None, Measure.REPS))
    workout = db.execute(
        "INSERT INTO workouts (started_at, source) VALUES ('t', 'test') RETURNING id"
    ).fetchone()[0]
    for position, exercise in enumerate((bench, bench, row), start=1):
        add_set(db, workout, exercise, position)

    detail = get_workout(db, workout)

    assert detail is not None
    assert [(block.position, block.name) for block in detail.exercises] == [
        (1, "Bench"),
        (2, "Bench"),
        (3, "Row"),
    ]


def test_workouts_with_the_same_start_time_are_separate_sessions(db: sqlite3.Connection) -> None:
    bench = upsert_exercise(db, ExerciseSpec("bench", "Bench", None, None, Measure.REPS))
    first, second = (
        db.execute(
            "INSERT INTO workouts (started_at, source) VALUES ('2026-01-01T10:00:00+00:00', 't') "
            "RETURNING id"
        ).fetchone()[0]
        for _ in range(2)
    )
    add_set(db, first, bench, 1)
    add_set(db, second, bench, 1)

    history = exercise_history(db, bench)

    assert history is not None
    assert [session.workout_id for session in history.sessions] == [second, first]


def test_an_exercise_repeated_in_a_workout_is_one_session_per_block(
    db: sqlite3.Connection,
) -> None:
    bench = upsert_exercise(db, ExerciseSpec("bench", "Bench", None, None, Measure.REPS))
    row = upsert_exercise(db, ExerciseSpec("row", "Row", None, None, Measure.REPS))
    workout = db.execute(
        "INSERT INTO workouts (started_at, source) VALUES ('2026-01-01T10:00:00+00:00', 't') "
        "RETURNING id"
    ).fetchone()[0]
    for position, exercise in ((1, bench), (2, row), (3, bench)):
        add_set(db, workout, exercise, position)
    db.execute(
        "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, reps) "
        "VALUES (?, ?, 3, 2, 3)",
        (workout, bench),
    )

    history = exercise_history(db, bench)

    assert history is not None
    assert history.exercise.workouts == 1
    assert history.sessions == [
        ExerciseSession(workout, 1, "2026-01-01T10:00:00+00:00", [set_view(1, 5)]),
        ExerciseSession(workout, 3, "2026-01-01T10:00:00+00:00", [set_view(1, 5), set_view(2, 3)]),
    ]


def test_summary_best_set_uses_reps_and_duration_for_ties(db: sqlite3.Connection) -> None:
    pulldown = upsert_exercise(db, ExerciseSpec("pulldown", "Pulldown", None, None, Measure.REPS))
    hang = upsert_exercise(db, ExerciseSpec("hang", "Hang", None, None, Measure.SECONDS))
    workout = db.execute(
        "INSERT INTO workouts (started_at, source) VALUES ('t', 'test') RETURNING id"
    ).fetchone()[0]
    rows = [
        (pulldown, 1, 1, 10, 50.0, None),
        (pulldown, 1, 2, 12, 50.0, None),  # same load, more reps: best
        (pulldown, 1, 3, 8, 50.0, None),
        (hang, 2, 1, None, None, 30.0),
        (hang, 2, 2, None, None, 50.0),  # longest: best
        (hang, 2, 3, None, None, 40.0),
    ]
    db.executemany(
        "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, "
        "reps, load_kg, duration_s) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(workout, *row) for row in rows],
    )

    (summary,) = list_workouts(db, 1)

    assert [(line.position, line.name, line.best.set_number) for line in summary.exercises] == [
        (1, "Pulldown", 2),
        (2, "Hang", 2),
    ]
