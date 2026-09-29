"""API application factory."""

from fastapi.testclient import TestClient

from trainer.api.app import create_app


def test_healthz_reports_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_schema_and_interactive_docs_are_not_served() -> None:
    client = TestClient(create_app())

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
