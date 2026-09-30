"""FastAPI application factory."""

from __future__ import annotations

import os
from contextlib import closing
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from trainer.api.history import router as history_router
from trainer.api.journal import router as journal_router
from trainer.api.settings import Settings, settings_from_env
from trainer.storage.database import connect, migrate

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.responses import Response

# Set by `tailscale serve` for requests from user-owned devices on the tailnet.
IDENTITY_HEADER = "Tailscale-User-Login"
PUBLIC_PATHS = frozenset({"/healthz"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application.

    Args:
        settings: explicit settings; by default they are read from the environment.

    Returns:
        The app: the database is migrated, every route except the liveness check
        answers only the owner's Tailscale identity, and the built web app (if
        configured) is served at ``/``.
    """
    settings = settings or settings_from_env(os.environ)
    with closing(connect(settings.database)) as conn:
        migrate(conn)

    app = FastAPI(openapi_url=None)  # no schema, so no /docs or /redoc either
    app.state.settings = settings

    @app.middleware("http")
    async def owner_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if request.headers.get(IDENTITY_HEADER) != settings.owner_login:
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # The journal router first: its /api/workouts/current must win over /{workout_id}.
    app.include_router(journal_router)
    app.include_router(history_router)
    if settings.web_dir is not None:
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True))
    return app
