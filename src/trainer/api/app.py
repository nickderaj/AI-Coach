"""FastAPI application factory."""

from __future__ import annotations

import hmac
import os
import threading
from contextlib import asynccontextmanager, closing
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from trainer.api.coach import router as coach_router
from trainer.api.history import router as history_router
from trainer.api.journal import router as journal_router
from trainer.api.profile import router as profile_router
from trainer.api.programs import router as programs_router
from trainer.api.settings import Settings, settings_from_env
from trainer.services.hermes import HermesGateway
from trainer.storage.database import connect, migrate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from starlette.responses import Response

    from trainer.services.coach import Gateway

# Set by `tailscale serve` for requests from user-owned devices on the tailnet.
IDENTITY_HEADER = "Tailscale-User-Login"
PUBLIC_PATHS = frozenset({"/healthz"})
# What the coach's tool server may do with the gateway's key instead of the
# owner's login: propose a program (it never touches the active one).
COACH_ROUTES = frozenset({("PUT", "/api/programs/proposal")})


def is_coach(request: Request, settings: Settings) -> bool:
    """Whether ``request`` is the coach's, on a route the coach may use.

    The coach proves itself with the gateway's key, which only the API and the
    coach hold, compared in constant time.
    """
    if settings.coach is None or (request.method, request.url.path) not in COACH_ROUTES:
        return False
    # why: header names are case-insensitive, so a mutant changing the name's case is equal
    given = request.headers.get("Authorization")  # pragma: no mutate
    expected = f"Bearer {settings.coach.key}"
    return given is not None and hmac.compare_digest(given.encode(), expected.encode())


def create_app(settings: Settings | None = None, coach_gateway: Gateway | None = None) -> FastAPI:
    """Build the API application.

    Args:
        settings: explicit settings; by default they are read from the environment.
        coach_gateway: the coach's Hermes gateway; by default the one in the
            settings, if any.

    Returns:
        The app: the database is migrated, every route except the liveness check
        answers only the owner's Tailscale identity, and the built web app (if
        configured) is served at ``/``.
    """
    settings = settings or settings_from_env(os.environ)
    with closing(connect(settings.database)) as conn:
        migrate(conn)

    @asynccontextmanager
    async def hold_the_database_open(_app: FastAPI) -> AsyncIterator[None]:
        # SQLite removes the -wal and -shm files when its last connection closes.
        # The coach's tool server reads from a read-only mount, where it cannot
        # create them, so one idle connection keeps them for as long as the API runs.
        with closing(connect(settings.database)):
            yield

    # No schema, so no /docs or /redoc either.
    app = FastAPI(openapi_url=None, lifespan=hold_the_database_open)
    app.state.settings = settings
    if coach_gateway is None and settings.coach is not None:
        coach_gateway = HermesGateway(settings.coach.url, settings.coach.key)
    app.state.coach_gateway = coach_gateway
    app.state.coach_turn = threading.Lock()

    @app.middleware("http")
    async def owner_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PUBLIC_PATHS or is_coach(request, settings):
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
    app.include_router(profile_router)
    app.include_router(coach_router)
    app.include_router(programs_router)
    if settings.web_dir is not None:
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True))
    return app
