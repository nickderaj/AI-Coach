"""The coach's read-only tools over the imported fixture log."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trainer.mcp.protocol import Json, ToolError
from trainer.mcp.tools import tools
from trainer.services.programs import ProgramIn, accept_proposal, propose_program
from trainer.storage.profile import Profile, save_profile

AUGUST = "2026-08-17T11:36:06+00:00"
JULY = "2026-07-09T10:47:23+00:00"


@pytest.fixture
def database(imported: sqlite3.Connection, tmp_path: Path) -> Path:
    """The fixture log on disk, with a body weight."""
    save_profile(imported, Profile(65.0))
    imported.commit()
    return tmp_path / "trainer.db"


def call(database: Path, name: str, arguments: Json | None = None) -> object:
    """Call a tool and round-trip its answer through JSON, as the model sees it."""
    answer = tools(database)[name].call(arguments or {})
    return json.loads(json.dumps(answer))


def ids(database: Path) -> dict[str, int]:
    exercises = call(database, "list_exercises")
    assert isinstance(exercises, list)
    return {exercise["name"]: exercise["id"] for exercise in exercises}


def test_the_tools_and_their_order(database: Path) -> None:
    assert list(tools(database)) == [
        "recent_workouts",
        "get_workout",
        "list_exercises",
        "exercise_history",
        "body_weight",
        "current_program",
    ]
    for name, tool in tools(database).items():
        assert tool.name == name
        assert tool.description.endswith(".")
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False


def test_argument_schemas(database: Path) -> None:
    schemas = {name: tool.input_schema for name, tool in tools(database).items()}

    limit = schemas["recent_workouts"]["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 10)
    assert schemas["get_workout"]["required"] == ["workout_id"]
    for name, argument in (("get_workout", "workout_id"), ("exercise_history", "exercise_id")):
        row_id = schemas[name]["properties"][argument]
        assert (row_id["type"], row_id["minimum"], row_id["maximum"]) == ("integer", 1, 2**63 - 1)
    sessions = schemas["exercise_history"]["properties"]["sessions"]
    assert (sessions["minimum"], sessions["maximum"], sessions["default"]) == (1, 100, 20)
    assert schemas["exercise_history"]["required"] == ["exercise_id"]
    assert schemas["list_exercises"].get("properties", {}) == {}
    assert schemas["body_weight"].get("properties", {}) == {}


def test_recent_workouts_newest_first(database: Path) -> None:
    workouts = call(database, "recent_workouts")

    assert isinstance(workouts, list)
    assert [workout["started_at"] for workout in workouts] == [AUGUST, JULY]
    august = workouts[0]
    assert august["set_count"] == 2
    assert august["volume_kg"] == 12 * 50 + 8 * 60.5  # pull-ups carry 93% of 65 kg
    assert [line["name"] for line in august["exercises"]] == ["Lat Pulldown", "Pull-up"]


def test_recent_workouts_respects_the_limit(database: Path) -> None:
    workouts = call(database, "recent_workouts", {"limit": 1})

    assert isinstance(workouts, list)
    assert [workout["started_at"] for workout in workouts] == [AUGUST]


def test_get_workout(database: Path) -> None:
    workouts = call(database, "recent_workouts")
    assert isinstance(workouts, list)

    july = call(database, "get_workout", {"workout_id": workouts[1]["id"]})

    assert isinstance(july, dict)
    assert july["notes"] == "first"
    bench, hang = july["exercises"]
    assert (bench["name"], bench["measure"], bench["carried_kg"]) == (
        "Barbell Bench Press",
        "reps",
        0,
    )
    assert [(s["reps"], s["load_kg"], s["rpe"]) for s in bench["sets"]] == [
        (8, 60.0, None),
        (6, 70.0, 8),
    ]
    assert (hang["measure"], hang["sets"][0]["duration_s"]) == ("seconds", 50.0)


def test_get_workout_that_does_not_exist(database: Path) -> None:
    with pytest.raises(ToolError, match=r"^there is no workout 999$"):
        call(database, "get_workout", {"workout_id": 999})


def test_list_exercises(database: Path) -> None:
    exercises = call(database, "list_exercises")

    assert isinstance(exercises, list)
    pull_up = next(exercise for exercise in exercises if exercise["name"] == "Pull-up")
    assert pull_up == {
        "id": pull_up["id"],
        "name": "Pull-up",
        "equipment": "bodyweight",
        "muscle_groups": "back,biceps",
        "measure": "reps",
        "workouts": 1,
        "last_done": AUGUST,
        "best_load_kg": None,
    }


def test_exercise_history(database: Path) -> None:
    history = call(database, "exercise_history", {"exercise_id": ids(database)["Pull-up"]})

    assert isinstance(history, dict)
    assert history["exercise"]["name"] == "Pull-up"
    assert history["carried_kg"] == 60.5
    assert [session["started_at"] for session in history["sessions"]] == [AUGUST]
    assert [s["reps"] for s in history["sessions"][0]["sets"]] == [8]


def test_exercise_history_keeps_the_newest_sessions(database: Path, tmp_path: Path) -> None:
    bench = ids(database)["Barbell Bench Press"]
    with closing(sqlite3.connect(tmp_path / "trainer.db")) as conn:
        workout = conn.execute(
            "INSERT INTO workouts (started_at, source) VALUES (?, 'test') RETURNING id", (AUGUST,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO workout_sets (workout_id, exercise_id, exercise_position, set_number, "
            "reps, load_kg) VALUES (?, ?, 1, 1, 5, 80)",
            (workout, bench),
        )
        conn.commit()

    newest = call(database, "exercise_history", {"exercise_id": bench, "sessions": 1})
    both = call(database, "exercise_history", {"exercise_id": bench})

    assert isinstance(newest, dict)
    assert isinstance(both, dict)
    assert [session["started_at"] for session in newest["sessions"]] == [AUGUST]
    assert [session["started_at"] for session in both["sessions"]] == [AUGUST, JULY]


def test_exercise_history_of_an_unknown_exercise(database: Path) -> None:
    with pytest.raises(ToolError, match=r"^there is no exercise 999$"):
        call(database, "exercise_history", {"exercise_id": 999})


def test_body_weight(database: Path) -> None:
    assert call(database, "body_weight") == {"bodyweight_kg": 65.0}


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("recent_workouts", {"limit": 0}, "limit: Input should be greater than or equal to 1"),
        ("recent_workouts", {"limit": 51}, "limit: Input should be less than or equal to 50"),
        ("get_workout", {}, "workout_id: Field required"),
        (
            "get_workout",
            {"workout_id": 0},
            "workout_id: Input should be greater than or equal to 1",
        ),
        ("get_workout", {"workout_id": 2**63}, "workout_id: Input should be less than or equal to"),
        ("exercise_history", {"exercise_id": 0}, "exercise_id: Input should be greater than or"),
        ("exercise_history", {"exercise_id": 2**63}, "exercise_id: Input should be less than or"),
        ("exercise_history", {"exercise_id": 1, "sessions": 101}, "sessions: Input should be"),
        ("body_weight", {"anything": 1}, "anything: Extra inputs are not permitted"),
    ],
)
def test_arguments_are_validated(database: Path, name: str, arguments: Json, message: str) -> None:
    with pytest.raises(ToolError, match=rf"^invalid arguments: {message}"):
        call(database, name, arguments)


def test_two_problems_are_both_reported(database: Path) -> None:
    with pytest.raises(ToolError) as caught:
        call(database, "exercise_history", {"sessions": 0, "x": 1})

    assert str(caught.value) == (
        "invalid arguments: exercise_id: Field required; "
        "sessions: Input should be greater than or equal to 1; "
        "x: Extra inputs are not permitted"
    )


def test_a_log_that_cannot_be_read_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "elsewhere" / "trainer.db"

    with pytest.raises(ToolError, match=r"^the training log cannot be read right now \(.+\)$"):
        call(missing, "body_weight")

    assert not missing.exists()  # read-only: nothing is created


def test_current_program_without_one(database: Path) -> None:
    assert call(database, "current_program") == {"active": None, "proposed": None, "next": None}


def test_current_program(imported: sqlite3.Connection, tmp_path: Path) -> None:
    bench = imported.execute(
        "SELECT id FROM exercises WHERE name = 'barbell bench press'"
    ).fetchone()[0]
    imported.commit()
    day = {
        "name": "Push",
        "blocks": [{"exercises": [{"exercise_id": bench, "sets": 3, "rep_min": 8, "rep_max": 10}]}],
    }
    now = datetime(2026, 10, 1, tzinfo=UTC)
    active = propose_program(
        imported, ProgramIn.model_validate({"name": "Now", "days": [day]}), now
    )
    accept_proposal(imported, active.id, now)
    propose_program(imported, ProgramIn.model_validate({"name": "Next", "days": [day, day]}), now)

    answer = call(tmp_path / "trainer.db", "current_program")

    assert isinstance(answer, dict)
    assert answer["active"]["name"] == "Now"
    assert answer["active"]["days"][0]["blocks"][0]["exercises"][0]["exercise_id"] == bench
    assert answer["proposed"]["name"] == "Next"
    assert answer["next"] == {"week": 1, "day": 1}
