"""Push subscriptions, the inbox and a test notice through the API."""

import base64
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from trainer.api.app import create_app
from trainer.api.settings import Settings
from trainer.storage.database import connect, migrate

OWNER = "owner@example.com"
AS_OWNER = {"Tailscale-User-Login": OWNER}
APPLE = "https://web.push.apple.com/QGuT8ar"
P256DH = base64.urlsafe_b64encode(b"\x04" + bytes(64)).decode()
SERVER = base64.urlsafe_b64encode(b"\x04" + bytes(range(1, 65))).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(bytes(16)).decode()
SUBSCRIPTION = {
    "endpoint": APPLE,
    "keys": {"p256dh": P256DH, "auth": AUTH},
    "server_key": SERVER,
}


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "trainer.db"
    with closing(connect(path)) as conn:
        migrate(conn)
    return path


@pytest.fixture
def client(database: Path) -> TestClient:
    return TestClient(create_app(Settings(database, OWNER, push_key=SERVER)))


def subscriptions(database: Path) -> list[str]:
    with closing(sqlite3.connect(database)) as conn:
        return [row[0] for row in conn.execute("SELECT endpoint FROM push_subscriptions")]


def test_the_key_to_subscribe_with(client: TestClient) -> None:
    response = client.get("/api/push/key", headers=AS_OWNER)

    assert response.status_code == 200
    assert response.json() == {"key": SERVER}


def test_without_a_key_notifications_are_not_set_up(database: Path) -> None:
    client = TestClient(create_app(Settings(database, OWNER)))

    response = client.get("/api/push/key", headers=AS_OWNER)

    assert response.status_code == 503
    assert response.json() == {"detail": "notifications are not set up"}


def test_subscribe_and_unsubscribe(client: TestClient, database: Path) -> None:
    put = client.put("/api/push/subscription", json=SUBSCRIPTION, headers=AS_OWNER)
    again = client.put("/api/push/subscription", json=SUBSCRIPTION, headers=AS_OWNER)

    assert (put.status_code, again.status_code) == (204, 204)
    assert put.content == b""
    assert subscriptions(database) == [APPLE]

    path = f"/api/push/subscription?endpoint={quote(APPLE, safe='')}"
    for _ in range(2):  # idempotent
        deleted = client.delete(path, headers=AS_OWNER)
        assert deleted.status_code == 204
    assert subscriptions(database) == []


def test_a_subscription_elsewhere_is_refused(client: TestClient, database: Path) -> None:
    body = {**SUBSCRIPTION, "endpoint": "https://127.0.0.1/api/programs"}

    response = client.put("/api/push/subscription", json=body, headers=AS_OWNER)

    assert response.status_code == 422
    assert subscriptions(database) == []


def test_a_subscription_made_with_an_old_server_key_is_refused(
    client: TestClient, database: Path
) -> None:
    old = base64.urlsafe_b64encode(b"\x04" + bytes(64)).decode()
    body = {**SUBSCRIPTION, "server_key": old}

    response = client.put("/api/push/subscription", json=body, headers=AS_OWNER)

    assert response.status_code == 409
    assert response.json() == {"detail": "subscribed with another server key; subscribe again"}
    assert subscriptions(database) == []


def test_without_a_key_nothing_can_subscribe(database: Path) -> None:
    client = TestClient(create_app(Settings(database, OWNER)))

    response = client.put("/api/push/subscription", json=SUBSCRIPTION, headers=AS_OWNER)

    assert response.status_code == 503
    assert subscriptions(database) == []


def test_unsubscribing_needs_a_bounded_endpoint(client: TestClient) -> None:
    missing = client.delete("/api/push/subscription", headers=AS_OWNER)
    long = client.delete(f"/api/push/subscription?endpoint={'x' * 2049}", headers=AS_OWNER)

    assert (missing.status_code, long.status_code) == (422, 422)


def test_a_test_notice_is_in_the_inbox_at_once(client: TestClient) -> None:
    posted = client.post("/api/push/test", headers=AS_OWNER)

    assert posted.status_code == 201
    notice_id = posted.json()["id"]
    inbox = client.get("/api/inbox", headers=AS_OWNER).json()
    assert inbox["unread"] == 1
    (notice,) = inbox["notices"]
    assert notice == {
        "id": notice_id,
        "kind": "test",
        "title": "Notifications are on",
        "body": "This is how the trainer will reach you.",
        "at": notice["at"],
        "read": False,
        "route": "#/inbox",
    }
    assert notice["at"].endswith("+00:00")


def test_seen_marks_a_notice_read(client: TestClient) -> None:
    notice_id = client.post("/api/push/test", headers=AS_OWNER).json()["id"]

    seen = client.post(f"/api/inbox/{notice_id}/seen", headers=AS_OWNER)

    assert seen.status_code == 204
    inbox = client.get("/api/inbox", headers=AS_OWNER).json()
    assert inbox["unread"] == 0
    assert inbox["notices"][0]["read"] is True


@pytest.mark.parametrize(("notice_id", "status"), [(99, 404), (0, 422), (2**63, 422)])
def test_seeing_a_missing_notice(client: TestClient, notice_id: int, status: int) -> None:
    response = client.post(f"/api/inbox/{notice_id}/seen", headers=AS_OWNER)

    assert response.status_code == status
    if status == 404:
        assert response.json() == {"detail": "no notice has id 99"}


def test_read_all(client: TestClient) -> None:
    client.post("/api/push/test", headers=AS_OWNER)
    client.post("/api/push/test", headers=AS_OWNER)

    response = client.post("/api/inbox/read", headers=AS_OWNER)

    assert response.status_code == 204
    assert client.get("/api/inbox", headers=AS_OWNER).json()["unread"] == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/push/key"),
        ("PUT", "/api/push/subscription"),
        ("DELETE", f"/api/push/subscription?endpoint={APPLE}"),
        ("POST", "/api/push/test"),
        ("GET", "/api/inbox"),
        ("POST", "/api/inbox/1/seen"),
        ("POST", "/api/inbox/read"),
    ],
)
def test_notifications_are_owner_only(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json=SUBSCRIPTION)

    assert response.status_code == 403
