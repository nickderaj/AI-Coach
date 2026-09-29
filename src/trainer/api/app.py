"""FastAPI application factory."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the API application.

    Returns:
        The configured application, with a liveness route for deploy checks.
    """
    app = FastAPI(openapi_url=None)  # no schema, so no /docs or /redoc either

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
