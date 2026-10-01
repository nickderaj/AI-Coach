"""Program endpoints, and workouts and sets trained from a program."""

from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from trainer.api.app import create_app
from trainer.api.settings import CoachSettings, Settings

OWNER = {"Tailscale-User-Login": "owner@example.com"}
W1 = "11111111-1111-4111-8111-111111111111"
S1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
S2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
COACH = {"Authorization": "Bearer gateway-key"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(Settings(database=tmp_path / "trainer.db", owner_login="owner@example.com"))
    )


def new_exercise(client: TestClient, name: str, equipment: str = "barbell") -> int:
    body = {"name": name, "equipment": equipment}
    response = client.post("/api/exercises", json=body, headers=OWNER)
    assert response.status_code == 201, response.text
    exercise_id: int = response.json()["id"]
    return exercise_id


def program_body(bench: int, row: int) -> dict[str, Any]:
    return {
        "name": "Full Body",
        "days": [
            {
                "name": "A",
                "blocks": [
                    {
                        "exercises": [
                            {"exercise_id": bench, "sets": 3, "rep_min": 8, "rep_max": 10},
                        ]
                    },
                    {
                        "rest_s": 60,
                        "exercises": [
                            {"exercise_id": row, "sets": 2, "rep_min": 10, "rep_max": 12},
                            {"exercise_id": bench, "sets": 2, "rep_min": 12, "rep_max": 15},
                        ],
                    },
                ],
            },
            {
                "name": "B",
                "blocks": [
                    {
                        "exercises": [
                            {
                                "exercise_id": row,
                                "sets": 3,
                                "rep_min": 8,
                                "rep_max": 10,
                                "start_load_kg": 50,
                            }
                        ]
                    }
                ],
            },
        ],
    }


@pytest.fixture
def ids(client: TestClient) -> tuple[int, int]:
    return new_exercise(client, "Bench Press"), new_exercise(client, "Cable Row", "cable")


def propose(client: TestClient, ids: tuple[int, int]) -> dict[str, Any]:
    response = client.put("/api/programs/proposal", json=program_body(*ids), headers=OWNER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def accept(client: TestClient, program_id: int) -> dict[str, Any]:
    response = client.post(f"/api/programs/{program_id}/accept", headers=OWNER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/programs"),
        ("PUT", "/api/programs/proposal"),
        ("POST", "/api/programs/1/decline"),
        ("POST", "/api/programs/1/accept"),
        ("GET", "/api/today"),
    ],
)
def test_owner_only(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path, json={}).status_code == 403


def test_no_programs_yet(client: TestClient) -> None:
    assert client.get("/api/programs", headers=OWNER).json() == {
        "active": None,
        "proposed": None,
        "next": None,
    }
    response = client.get("/api/today", headers=OWNER)
    assert response.status_code == 200
    assert response.json() is None


def test_propose_then_accept(client: TestClient, ids: tuple[int, int]) -> None:
    proposed = propose(client, ids)

    assert proposed["status"] == "proposed"
    assert proposed["training_weeks"] == 6
    assert proposed["started_at"] is None
    assert proposed["created_at"].endswith("+00:00")
    day_a = proposed["days"][0]
    assert [len(block["exercises"]) for block in day_a["blocks"]] == [1, 2]
    assert day_a["blocks"][1]["rest_s"] == 60
    assert day_a["blocks"][0]["rest_s"] == 90
    assert day_a["blocks"][1]["exercises"][0] | {"id": 0} == {
        "id": 0,
        "exercise_id": ids[1],
        "name": "Cable Row",
        "equipment": "cable",
        "measure": "reps",
        "sets": 2,
        "rep_min": 10,
        "rep_max": 12,
        "start_load_kg": None,
        "notes": None,
        "increment_kg": 2.5,
    }
    listed = client.get("/api/programs", headers=OWNER).json()
    assert (listed["active"], listed["proposed"], listed["next"]) == (None, proposed, None)

    active = accept(client, proposed["id"])

    assert active["status"] == "active"
    assert active["started_at"].endswith("+00:00")
    listed = client.get("/api/programs", headers=OWNER).json()
    assert (listed["active"], listed["proposed"], listed["next"]) == (
        active,
        None,
        {"week": 1, "day": 1},
    )


def test_accepting_while_the_program_is_being_trained(
    client: TestClient, ids: tuple[int, int]
) -> None:
    active = accept(client, propose(client, ids)["id"])
    link = {"day_id": active["days"][0]["id"], "week": 1}
    started = {"started_at": "2026-10-01T09:00:00Z", "program": link}
    client.put(f"/api/workouts/{W1}", json=started, headers=OWNER)
    new = propose(client, ids)

    response = client.post(f"/api/programs/{new['id']}/accept", headers=OWNER)

    assert response.status_code == 409
    assert response.json() == {"detail": "finish or discard the workout in progress first"}


def test_accepting_what_is_not_the_proposal(client: TestClient, ids: tuple[int, int]) -> None:
    active = accept(client, propose(client, ids)["id"])

    response = client.post(f"/api/programs/{active['id']}/accept", headers=OWNER)

    assert response.status_code == 409
    assert response.json() == {"detail": f"program {active['id']} is not the proposal"}


@pytest.mark.parametrize("program_id", ["0", str(2**63), "x"])
def test_accepting_a_bad_id(client: TestClient, program_id: str) -> None:
    response = client.post(f"/api/programs/{program_id}/accept", headers=OWNER)

    assert response.status_code == 422


def test_decline(client: TestClient, ids: tuple[int, int]) -> None:
    shown = propose(client, ids)

    declined = client.post(f"/api/programs/{shown['id']}/decline", headers=OWNER)
    again = client.post(f"/api/programs/{shown['id']}/decline", headers=OWNER)

    assert declined.status_code == 204
    assert again.status_code == 409
    assert again.json() == {"detail": f"program {shown['id']} is not the proposal"}
    assert client.get("/api/programs", headers=OWNER).json()["proposed"] is None


def test_decline_only_the_proposal_shown(client: TestClient, ids: tuple[int, int]) -> None:
    shown = propose(client, ids)
    newer = propose(client, ids)  # the coach replaced it meanwhile

    response = client.post(f"/api/programs/{shown['id']}/decline", headers=OWNER)

    assert response.status_code == 409
    assert client.get("/api/programs", headers=OWNER).json()["proposed"] == newer


@pytest.mark.parametrize("program_id", ["0", str(2**63), "x"])
def test_declining_a_bad_id(client: TestClient, program_id: str) -> None:
    assert client.post(f"/api/programs/{program_id}/decline", headers=OWNER).status_code == 422


def test_a_proposal_of_unknown_exercises(client: TestClient, ids: tuple[int, int]) -> None:
    response = client.put("/api/programs/proposal", json=program_body(ids[0], 99), headers=OWNER)

    assert response.status_code == 422
    assert response.json() == {"detail": "no exercise has id 99"}


def test_a_proposal_of_the_wrong_shape(client: TestClient, ids: tuple[int, int]) -> None:
    body = program_body(*ids)
    body["days"][0]["blocks"][0]["exercises"][0]["rep_max"] = 5

    response = client.put("/api/programs/proposal", json=body, headers=OWNER)

    assert response.status_code == 422


class TestTraining:
    @pytest.fixture
    def program(self, client: TestClient, ids: tuple[int, int]) -> dict[str, Any]:
        return accept(client, propose(client, ids)["id"])

    def start(self, client: TestClient, day_id: int, week: int = 1) -> httpx2.Response:
        return client.put(
            f"/api/workouts/{W1}",
            json={
                "started_at": "2026-10-01T09:00:00Z",
                "program": {"day_id": day_id, "week": week},
            },
            headers=OWNER,
        )

    def test_today(self, client: TestClient, program: dict[str, Any]) -> None:
        today = client.get("/api/today", headers=OWNER).json()

        assert {key: today[key] for key in ("program_id", "program_name", "days")} == {
            "program_id": program["id"],
            "program_name": "Full Body",
            "days": 2,
        }
        assert today["training_weeks"] == 6
        assert today["workout_client_id"] is None
        day = today["day"]
        assert (day["name"], day["week"], day["deload"]) == ("A", 1, False)
        exercise = day["blocks"][0]["exercises"][0]
        assert exercise["target"] == {"decision": "start", "load_kg": None, "reps": [8, 8, 8]}
        assert (exercise["last"], exercise["carried_kg"]) == (None, 0.0)

    def test_train_a_day(self, client: TestClient, program: dict[str, Any]) -> None:
        day = program["days"][0]
        slot = day["blocks"][0]["exercises"][0]

        started = self.start(client, day["id"])
        logged = client.put(
            f"/api/sets/{S1}",
            json={
                "workout_client_id": W1,
                "exercise_id": slot["exercise_id"],
                "block_exercise_id": slot["id"],
                "reps": 10,
                "load_kg": 60,
            },
            headers=OWNER,
        )

        assert started.status_code == 200
        assert (started.json()["program_day_id"], started.json()["program_week"]) == (day["id"], 1)
        assert logged.status_code == 200
        assert logged.json()["exercises"][0]["block_exercise_id"] == slot["id"]
        assert client.get("/api/today", headers=OWNER).json()["workout_client_id"] == W1

    @pytest.mark.parametrize(
        "link",
        [
            {"day_id": None},  # no week
            {"week": 1},  # no day
            {"day_id": 0, "week": 1},
            {"day_id": None, "week": 0},
            {"day_id": None, "week": 53},
        ],
    )
    def test_a_workout_names_a_day_and_its_week_together(
        self, client: TestClient, program: dict[str, Any], link: dict[str, int | None]
    ) -> None:
        real = {
            key: program["days"][0]["id"] if value is None else value for key, value in link.items()
        }
        body = {"started_at": "2026-10-01T09:00:00Z", "program": real}

        response = client.put(f"/api/workouts/{W1}", json=body, headers=OWNER)

        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)  # refused by the shape, not the day

    def test_a_finished_day_cannot_be_started_again(
        self, client: TestClient, program: dict[str, Any]
    ) -> None:
        day_id = program["days"][0]["id"]
        link = {"day_id": day_id, "week": 1}
        done = {"started_at": "2026-10-01T09:00:00Z", "ended_at": "2026-10-01T10:00:00Z"}
        client.put(f"/api/workouts/{W1}", json=done | {"program": link}, headers=OWNER)

        again = client.put(
            "/api/workouts/22222222-2222-4222-8222-222222222222",
            json={"started_at": "2026-10-02T09:00:00Z", "program": link},
            headers=OWNER,
        )

        assert again.status_code == 409
        assert again.json() == {"detail": f"week 1 of day {day_id} already has a workout"}

    def test_a_workout_of_a_missing_day(self, client: TestClient, program: dict[str, Any]) -> None:
        response = self.start(client, program["days"][1]["id"] + 100)

        assert response.status_code == 422
        assert response.json() == {"detail": "program day not found"}

    def test_week_bounds(self, client: TestClient, program: dict[str, Any]) -> None:
        day_id = program["days"][0]["id"]

        assert self.start(client, day_id, 52).json() == {"detail": "the program has 7 weeks"}
        assert self.start(client, day_id, 7).status_code == 200

    def test_a_workout_with_program_sets_keeps_its_day(
        self, client: TestClient, program: dict[str, Any]
    ) -> None:
        day = program["days"][0]
        slot = day["blocks"][0]["exercises"][0]
        self.start(client, day["id"])
        set_body = {
            "workout_client_id": W1,
            "exercise_id": slot["exercise_id"],
            "block_exercise_id": slot["id"],
            "reps": 10,
        }
        client.put(f"/api/sets/{S1}", json=set_body, headers=OWNER)

        cleared = client.put(
            f"/api/workouts/{W1}", json={"started_at": "2026-10-01T09:00:00Z"}, headers=OWNER
        )
        moved = self.start(client, program["days"][1]["id"])

        assert (cleared.status_code, moved.status_code) == (422, 422)
        assert moved.json() == {"detail": "the workout has sets for another program day"}
        assert client.put(f"/api/sets/{S1}", json=set_body, headers=OWNER).status_code == 200

    def test_a_set_for_another_days_exercise(
        self, client: TestClient, program: dict[str, Any]
    ) -> None:
        other = program["days"][1]["blocks"][0]["exercises"][0]
        self.start(client, program["days"][0]["id"])

        response = client.put(
            f"/api/sets/{S2}",
            json={
                "workout_client_id": W1,
                "exercise_id": other["exercise_id"],
                "block_exercise_id": other["id"],
                "reps": 10,
            },
            headers=OWNER,
        )

        assert response.status_code == 422
        assert response.json() == {
            "detail": "the program exercise is not on this workout's program day"
        }


class TestTheCoachsKey:
    """The coach's tool server proposes programs with the gateway's key, and does nothing else."""

    @pytest.fixture
    def coached(self, tmp_path: Path) -> TestClient:
        settings = Settings(
            database=tmp_path / "trainer.db",
            owner_login="owner@example.com",
            coach=CoachSettings("http://127.0.0.1:1", "gateway-key"),
        )
        return TestClient(create_app(settings))

    def test_it_may_propose(self, coached: TestClient) -> None:
        bench = new_exercise(coached, "Bench Press")
        body = program_body(bench, bench)

        response = coached.put("/api/programs/proposal", json=body, headers=COACH)

        assert response.status_code == 200
        assert response.json()["status"] == "proposed"

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/programs"),
            ("POST", "/api/programs/1/decline"),
            ("POST", "/api/programs/1/accept"),
            ("GET", "/api/today"),
            ("GET", "/api/workouts"),
            ("POST", "/api/coach/messages"),
        ],
    )
    def test_it_may_do_nothing_else(self, coached: TestClient, method: str, path: str) -> None:
        assert coached.request(method, path, json={}, headers=COACH).status_code == 403

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "gateway-key"},
            {"Authorization": "bearer gateway-key"},
            {"Authorization": "Bearer gateway-key "},
        ],
    )
    def test_only_with_the_key(self, coached: TestClient, headers: dict[str, str]) -> None:
        response = coached.put("/api/programs/proposal", json={}, headers=headers)

        assert response.status_code == 403

    def test_not_without_a_coach(self, client: TestClient) -> None:
        response = client.put(
            "/api/programs/proposal", json={}, headers={"Authorization": "Bearer "}
        )

        assert response.status_code == 403
