"""Write endpoints: workouts, sets and exercises from the app."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trainer.api.app import create_app
from trainer.api.settings import Settings

OWNER = {"Tailscale-User-Login": "owner@example.com"}
W1 = "11111111-1111-4111-8111-111111111111"
S1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
S2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

# Timestamps must not depend on the host's timezone (CI runs in UTC).
pytestmark = pytest.mark.usefixtures("far_east_timezone")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(Settings(database=tmp_path / "trainer.db", owner_login="owner@example.com"))
    )


def new_exercise(client: TestClient, name: str = "Goblet Squat", **extra: object) -> int:
    response = client.post("/api/exercises", json={"name": name, **extra}, headers=OWNER)
    assert response.status_code == 201, response.text
    exercise_id: int = response.json()["id"]
    return exercise_id


def start(client: TestClient, client_id: str = W1) -> dict[str, object]:
    response = client.put(
        f"/api/workouts/{client_id}",
        json={"started_at": "2026-09-30T09:00:00+01:00", "notes": "  legs  "},
        headers=OWNER,
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


class TestAccess:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/workouts/current"),
            ("PUT", f"/api/workouts/{W1}"),
            ("DELETE", f"/api/workouts/{W1}"),
            ("PUT", f"/api/sets/{S1}"),
            ("DELETE", f"/api/sets/{S1}"),
            ("POST", "/api/exercises"),
        ],
    )
    def test_writes_are_owner_only(self, client: TestClient, method: str, path: str) -> None:
        assert client.request(method, path, json={}).status_code == 403


class TestWorkouts:
    def test_no_current_workout(self, client: TestClient) -> None:
        response = client.get("/api/workouts/current", headers=OWNER)

        assert response.status_code == 200
        assert response.json() is None

    def test_start_then_resume_then_finish(self, client: TestClient) -> None:
        started = start(client)

        assert started["client_id"] == W1
        assert started["started_at"] == "2026-09-30T08:00:00+00:00"
        assert started["notes"] == "legs"
        assert client.get("/api/workouts/current", headers=OWNER).json()["client_id"] == W1

        finished = client.put(
            f"/api/workouts/{W1}",
            json={"started_at": "2026-09-30T08:00:00Z", "ended_at": "2026-09-30T09:10:00Z"},
            headers=OWNER,
        )

        assert finished.json()["ended_at"] == "2026-09-30T09:10:00+00:00"
        assert client.get("/api/workouts/current", headers=OWNER).json() is None
        assert client.get("/api/workouts", headers=OWNER).json()[0]["id"] == started["id"]

    def test_ending_before_starting_is_rejected(self, client: TestClient) -> None:
        response = client.put(
            f"/api/workouts/{W1}",
            json={"started_at": "2026-09-30T09:00:00Z", "ended_at": "2026-09-30T08:00:00Z"},
            headers=OWNER,
        )

        assert response.status_code == 422
        assert response.json() == {"detail": "a workout cannot end before it starts"}

    @pytest.mark.parametrize(
        "body",
        [
            {"started_at": "2026-09-30T09:00:00"},  # no timezone
            {},
            {"started_at": "2026-09-30T09:00:00Z", "notes": "x" * 1001},
        ],
    )
    def test_invalid_workouts_are_rejected(
        self, client: TestClient, body: dict[str, object]
    ) -> None:
        assert client.put(f"/api/workouts/{W1}", json=body, headers=OWNER).status_code == 422

    def test_client_ids_must_be_uuids(self, client: TestClient) -> None:
        response = client.put(
            "/api/workouts/not-a-uuid", json={"started_at": "2026-09-30T09:00:00Z"}, headers=OWNER
        )

        assert response.status_code == 422

    def test_delete_workout_is_idempotent(self, client: TestClient) -> None:
        start(client)

        assert client.delete(f"/api/workouts/{W1}", headers=OWNER).status_code == 204
        assert client.delete(f"/api/workouts/{W1}", headers=OWNER).status_code == 204
        assert client.get("/api/workouts", headers=OWNER).json() == []


class TestSets:
    def test_log_and_correct_a_set(self, client: TestClient) -> None:
        exercise_id = new_exercise(client)
        start(client)
        body = {"workout_client_id": W1, "exercise_id": exercise_id, "reps": 10, "load_kg": 24}

        logged = client.put(f"/api/sets/{S1}", json=body, headers=OWNER)
        replayed = client.put(f"/api/sets/{S1}", json=body, headers=OWNER)
        corrected = client.put(
            f"/api/sets/{S1}", json={**body, "reps": 8, "rpe": 9, "notes": " ok "}, headers=OWNER
        )

        assert logged.status_code == replayed.status_code == corrected.status_code == 200
        assert replayed.json() == logged.json()
        (block,) = corrected.json()["exercises"]
        assert block["sets"] == [
            {
                "set_number": 1,
                "reps": 8,
                "load_kg": 24.0,
                "duration_s": None,
                "rpe": 9,
                "notes": "ok",
                "client_id": S1,
            }
        ]

    def test_timed_set(self, client: TestClient) -> None:
        exercise_id = new_exercise(client, "Plank", measure="seconds")
        start(client)

        response = client.put(
            f"/api/sets/{S1}",
            json={"workout_client_id": W1, "exercise_id": exercise_id, "duration_s": 45},
            headers=OWNER,
        )

        assert response.json()["exercises"][0]["sets"][0]["duration_s"] == 45.0

    @pytest.mark.parametrize(
        "extra",
        [
            {},  # neither reps nor duration
            {"reps": -1},
            {"reps": 10_001},
            {"reps": 5, "load_kg": -1},
            {"reps": 5, "load_kg": 1_001},
            {"duration_s": 86_401},
            {"reps": 5, "rpe": 0},
            {"reps": 5, "rpe": 11},
            {"reps": 5, "notes": "x" * 1001},
        ],
    )
    def test_invalid_sets_are_rejected(self, client: TestClient, extra: dict[str, object]) -> None:
        exercise_id = new_exercise(client)
        start(client)
        body = {"workout_client_id": W1, "exercise_id": exercise_id, **extra}

        assert client.put(f"/api/sets/{S1}", json=body, headers=OWNER).status_code == 422

    @pytest.mark.parametrize(
        ("extra", "field", "value"),
        [
            ({"reps": 0}, "reps", 0),
            ({"reps": 10_000}, "reps", 10_000),
            ({"reps": 1, "load_kg": 0}, "load_kg", 0.0),
            ({"reps": 1, "load_kg": 1_000}, "load_kg", 1000.0),
            ({"duration_s": 0}, "duration_s", 0.0),
            ({"duration_s": 86_400}, "duration_s", 86400.0),
            ({"reps": 1, "rpe": 1}, "rpe", 1),
            ({"reps": 1, "rpe": 10}, "rpe", 10),
            ({"reps": 1, "notes": "x" * 1000}, "notes", "x" * 1000),
        ],
    )
    def test_bounds_are_inclusive(
        self, client: TestClient, extra: dict[str, object], field: str, value: object
    ) -> None:
        exercise_id = new_exercise(client)
        start(client)
        body = {"workout_client_id": W1, "exercise_id": exercise_id, **extra}

        response = client.put(f"/api/sets/{S1}", json=body, headers=OWNER)

        assert response.status_code == 200, response.text
        assert response.json()["exercises"][0]["sets"][0][field] == value

    def test_unknown_workout_or_exercise(self, client: TestClient) -> None:
        exercise_id = new_exercise(client)
        body = {"workout_client_id": W1, "exercise_id": exercise_id, "reps": 5}

        missing_workout = client.put(f"/api/sets/{S1}", json=body, headers=OWNER)
        start(client)
        missing_exercise = client.put(
            f"/api/sets/{S1}", json={**body, "exercise_id": 999}, headers=OWNER
        )

        assert (missing_workout.status_code, missing_workout.json()) == (
            404,
            {"detail": "workout not found"},
        )
        assert (missing_exercise.status_code, missing_exercise.json()) == (
            404,
            {"detail": "exercise not found"},
        )

    def test_moving_a_set_to_another_exercise_conflicts(self, client: TestClient) -> None:
        squat, plank = new_exercise(client), new_exercise(client, "Plank")
        start(client)
        body = {"workout_client_id": W1, "exercise_id": squat, "reps": 5}
        client.put(f"/api/sets/{S1}", json=body, headers=OWNER)

        response = client.put(f"/api/sets/{S1}", json={**body, "exercise_id": plank}, headers=OWNER)

        assert response.status_code == 409
        assert response.json() == {"detail": f"set {S1} belongs to another workout or exercise"}

    def test_delete_set_is_idempotent(self, client: TestClient) -> None:
        exercise_id = new_exercise(client)
        start(client)
        body = {"workout_client_id": W1, "exercise_id": exercise_id, "reps": 5}
        client.put(f"/api/sets/{S1}", json=body, headers=OWNER)
        client.put(f"/api/sets/{S2}", json=body, headers=OWNER)

        assert client.delete(f"/api/sets/{S1}", headers=OWNER).status_code == 204
        assert client.delete(f"/api/sets/{S1}", headers=OWNER).status_code == 204
        current = client.get("/api/workouts/current", headers=OWNER).json()
        assert [s["client_id"] for s in current["exercises"][0]["sets"]] == [S2]


class TestExercises:
    def test_create(self, client: TestClient) -> None:
        response = client.post(
            "/api/exercises",
            json={"name": " Goblet Squat ", "equipment": "kettlebell", "muscle_groups": "quads"},
            headers=OWNER,
        )

        assert response.status_code == 201
        body = response.json()
        assert body == {
            "id": body["id"],
            "name": "Goblet Squat",
            "equipment": "kettlebell",
            "muscle_groups": "quads",
            "measure": "reps",
            "workouts": 0,
            "last_done": None,
            "best_load_kg": None,
        }

    def test_exact_duplicate_is_refused(self, client: TestClient) -> None:
        existing = new_exercise(client, equipment="kettlebell")

        response = client.post(
            "/api/exercises", json={"name": "goblet squat", "allow_similar": True}, headers=OWNER
        )

        assert response.status_code == 409
        assert response.json() == {
            "detail": {
                "reason": "exists",
                "matches": [{"id": existing, "name": "Goblet Squat", "equipment": "kettlebell"}],
            }
        }

    def test_similar_needs_confirmation(self, client: TestClient) -> None:
        existing = new_exercise(client, "Barbell Bench Press", equipment="barbell")

        refused = client.post("/api/exercises", json={"name": "Bench Press"}, headers=OWNER)
        confirmed = client.post(
            "/api/exercises", json={"name": "Bench Press", "allow_similar": True}, headers=OWNER
        )

        assert refused.status_code == 409
        assert refused.json()["detail"] == {
            "reason": "similar",
            "matches": [{"id": existing, "name": "Barbell Bench Press", "equipment": "barbell"}],
        }
        assert confirmed.status_code == 201

    @pytest.mark.parametrize(
        "body",
        [
            {"name": "x"},
            {"name": "x" * 61},
            {"name": "   "},
            {"name": "Squat", "equipment": "trampoline"},
            {"name": "Squat", "measure": "laps"},
            {"name": "Squat", "muscle_groups": "x" * 201},
        ],
    )
    def test_invalid_exercises(self, client: TestClient, body: dict[str, object]) -> None:
        assert client.post("/api/exercises", json=body, headers=OWNER).status_code == 422

    @pytest.mark.parametrize("name", ["ab", "x" * 60])
    def test_name_length_bounds_are_inclusive(self, client: TestClient, name: str) -> None:
        assert new_exercise(client, name) > 0
