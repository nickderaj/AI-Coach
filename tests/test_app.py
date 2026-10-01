"""The API application: settings, owner-only access, history routes, web app."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trainer.api.app import create_app
from trainer.api.settings import Settings, SettingsError, settings_from_env
from trainer.services.import_v1 import import_v1
from trainer.storage.database import MIGRATIONS, connect, migrate, schema_version

OWNER = "owner@example.com"
AS_OWNER = {"Tailscale-User-Login": OWNER}


@pytest.fixture
def database(tmp_path: Path, v1: sqlite3.Connection) -> Path:
    path = tmp_path / "data" / "trainer.db"
    path.parent.mkdir()
    with closing(connect(path)) as conn:
        migrate(conn)
        import_v1(v1, conn)
    return path


@pytest.fixture
def client(database: Path) -> TestClient:
    return TestClient(create_app(Settings(database=database, owner_login=OWNER)))


class TestSettings:
    def test_from_env(self) -> None:
        settings = settings_from_env(
            {
                "TRAINER_DATA_DIR": "/srv/t",
                "TRAINER_OWNER_LOGIN": OWNER,
                "TRAINER_WEB_DIR": "/opt/t/web",
            }
        )

        assert settings == Settings(Path("/srv/t/trainer.db"), OWNER, Path("/opt/t/web"))

    def test_web_dir_is_optional(self) -> None:
        settings = settings_from_env({"TRAINER_DATA_DIR": "/srv/t", "TRAINER_OWNER_LOGIN": OWNER})

        assert settings.web_dir is None

    @pytest.mark.parametrize(
        "env",
        [
            {"TRAINER_OWNER_LOGIN": OWNER},
            {"TRAINER_DATA_DIR": "/srv/t"},
            {"TRAINER_DATA_DIR": "", "TRAINER_OWNER_LOGIN": OWNER},
            {"TRAINER_DATA_DIR": "/srv/t", "TRAINER_OWNER_LOGIN": ""},
        ],
    )
    def test_data_dir_and_owner_are_required(self, env: dict[str, str]) -> None:
        with pytest.raises(
            SettingsError, match=r"^TRAINER_DATA_DIR and TRAINER_OWNER_LOGIN must be set$"
        ):
            settings_from_env(env)

    def test_create_app_reads_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TRAINER_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("TRAINER_OWNER_LOGIN", OWNER)
        monkeypatch.delenv("TRAINER_WEB_DIR", raising=False)

        client = TestClient(create_app())

        assert client.get("/api/workouts", headers=AS_OWNER).json() == []


def test_create_app_migrates_a_new_database(tmp_path: Path) -> None:
    path = tmp_path / "trainer.db"

    create_app(Settings(database=path, owner_login=OWNER))

    with closing(connect(path)) as conn:
        assert schema_version(conn) == len(MIGRATIONS)


class TestAccess:
    def test_healthz_is_public(self, client: TestClient) -> None:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.parametrize(
        "headers",
        [{}, {"Tailscale-User-Login": "someone@example.com"}, {"Tailscale-User-Login": ""}],
    )
    @pytest.mark.parametrize("path", ["/api/workouts", "/api/exercises", "/", "/nope"])
    def test_everything_else_is_owner_only(
        self, client: TestClient, headers: dict[str, str], path: str
    ) -> None:
        response = client.get(path, headers=headers)

        assert response.status_code == 403
        assert response.json() == {"detail": "forbidden"}

    def test_schema_and_interactive_docs_are_not_served(self, client: TestClient) -> None:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path, headers=AS_OWNER).status_code == 404, path


class TestHistory:
    def test_workouts(self, client: TestClient) -> None:
        body = client.get("/api/workouts", headers=AS_OWNER).json()

        assert [
            (w["started_at"], [e["name"] for e in w["exercises"]], w["set_count"], w["volume_kg"])
            for w in body
        ] == [
            ("2026-08-17T11:36:06+00:00", ["Lat Pulldown", "Pull-up"], 2, 600.0),
            ("2026-07-09T10:47:23+00:00", ["Barbell Bench Press", "Dead Hang"], 3, 900.0),
        ]
        assert set(body[0]) == {
            "id",
            "started_at",
            "ended_at",
            "exercises",
            "set_count",
            "volume_kg",
        }
        assert body[1]["exercises"][0] == {
            "position": 1,
            "name": "Barbell Bench Press",
            "measure": "reps",
            "sets": 2,
            "best": {
                "set_number": 2,
                "reps": 6,
                "load_kg": 70.0,
                "duration_s": None,
                "rpe": 8,
                "notes": "grindy",
                "client_id": None,
            },
        }

    @pytest.mark.parametrize(("limit", "count"), [(1, 1), (500, 2)])
    def test_workouts_limit(self, client: TestClient, limit: int, count: int) -> None:
        response = client.get(f"/api/workouts?limit={limit}", headers=AS_OWNER)

        assert len(response.json()) == count

    @pytest.mark.parametrize("limit", [0, 501])
    def test_workouts_limit_is_bounded(self, client: TestClient, limit: int) -> None:
        assert client.get(f"/api/workouts?limit={limit}", headers=AS_OWNER).status_code == 422

    def test_workout_detail(self, client: TestClient) -> None:
        newest = client.get("/api/workouts", headers=AS_OWNER).json()[0]["id"]

        body = client.get(f"/api/workouts/{newest}", headers=AS_OWNER).json()

        assert body["notes"] == "good"
        assert [(e["position"], e["name"], e["measure"]) for e in body["exercises"]] == [
            (1, "Lat Pulldown", "reps"),
            (2, "Pull-up", "reps"),
        ]
        assert body["exercises"][0]["sets"] == [
            {
                "set_number": 1,
                "reps": 12,
                "load_kg": 50.0,
                "duration_s": None,
                "rpe": None,
                "notes": None,
                "client_id": None,
            }
        ]

    def test_missing_workout(self, client: TestClient) -> None:
        response = client.get("/api/workouts/999", headers=AS_OWNER)

        assert response.status_code == 404
        assert response.json() == {"detail": "workout not found"}

    def test_exercises(self, client: TestClient) -> None:
        body = client.get("/api/exercises", headers=AS_OWNER).json()

        assert [e["name"] for e in body] == [
            "Lat Pulldown",
            "Pull-up",
            "Barbell Bench Press",
            "Dead Hang",
        ]
        assert body[0] == {
            "id": body[0]["id"],
            "name": "Lat Pulldown",
            "equipment": "cable",
            "muscle_groups": "back,biceps",
            "measure": "reps",
            "workouts": 1,
            "last_done": "2026-08-17T11:36:06+00:00",
            "best_load_kg": 50.0,
        }

    def test_exercise_history(self, client: TestClient) -> None:
        bench = next(
            e["id"]
            for e in client.get("/api/exercises", headers=AS_OWNER).json()
            if e["name"] == "Barbell Bench Press"
        )

        body = client.get(f"/api/exercises/{bench}/history", headers=AS_OWNER).json()

        assert body["exercise"]["name"] == "Barbell Bench Press"
        assert [s["started_at"] for s in body["sessions"]] == ["2026-07-09T10:47:23+00:00"]
        assert [(s["reps"], s["load_kg"]) for s in body["sessions"][0]["sets"]] == [
            (8, 60.0),
            (6, 70.0),
        ]

    def test_bodyweight_exercises_use_the_profile(self, client: TestClient) -> None:
        assert client.get("/api/profile", headers=AS_OWNER).json() == {"bodyweight_kg": None}

        saved = client.put("/api/profile", json={"bodyweight_kg": 65}, headers=AS_OWNER)

        assert saved.status_code == 200
        assert saved.json() == {"bodyweight_kg": 65.0}
        assert client.get("/api/profile", headers=AS_OWNER).json() == {"bodyweight_kg": 65.0}
        newest = client.get("/api/workouts", headers=AS_OWNER).json()[0]
        assert newest["volume_kg"] == 12 * 50 + 8 * 65
        detail = client.get(f"/api/workouts/{newest['id']}", headers=AS_OWNER).json()
        assert [e["carried_kg"] for e in detail["exercises"]] == [0.0, 65.0]
        pull_up = next(
            e["id"]
            for e in client.get("/api/exercises", headers=AS_OWNER).json()
            if e["name"] == "Pull-up"
        )
        history = client.get(f"/api/exercises/{pull_up}/history", headers=AS_OWNER).json()
        assert history["carried_kg"] == 65.0

    @pytest.mark.parametrize("weight", [0, -1, 501, "heavy"])
    def test_profile_rejects_impossible_body_weights(
        self, client: TestClient, weight: object
    ) -> None:
        response = client.put("/api/profile", json={"bodyweight_kg": weight}, headers=AS_OWNER)

        assert response.status_code == 422

    def test_profile_body_weight_can_be_cleared(self, client: TestClient) -> None:
        client.put("/api/profile", json={"bodyweight_kg": 65}, headers=AS_OWNER)

        cleared = client.put("/api/profile", json={}, headers=AS_OWNER)

        assert cleared.json() == {"bodyweight_kg": None}

    def test_missing_exercise(self, client: TestClient) -> None:
        response = client.get("/api/exercises/999/history", headers=AS_OWNER)

        assert response.status_code == 404
        assert response.json() == {"detail": "exercise not found"}


class TestWebApp:
    @pytest.fixture
    def web_client(self, database: Path, tmp_path: Path) -> TestClient:
        web = tmp_path / "web"
        (web / "assets").mkdir(parents=True)
        (web / "index.html").write_text("<!doctype html><title>Trainer</title>")
        (web / "assets" / "app.js").write_text("console.log(1)")
        settings = Settings(database=database, owner_login=OWNER, web_dir=web)
        return TestClient(create_app(settings))

    def test_index_and_assets_are_served_to_the_owner(self, web_client: TestClient) -> None:
        index = web_client.get("/", headers=AS_OWNER)
        asset = web_client.get("/assets/app.js", headers=AS_OWNER)

        assert index.status_code == 200
        assert "<title>Trainer</title>" in index.text
        assert asset.text == "console.log(1)"

    def test_api_routes_take_precedence_over_the_web_app(self, web_client: TestClient) -> None:
        assert web_client.get("/api/workouts?limit=1", headers=AS_OWNER).status_code == 200
        assert web_client.get("/healthz").json() == {"status": "ok"}

    def test_web_app_is_owner_only(self, web_client: TestClient) -> None:
        assert web_client.get("/").status_code == 403

    def test_without_a_web_dir_nothing_is_served_at_root(self, client: TestClient) -> None:
        assert client.get("/", headers=AS_OWNER).status_code == 404
