"""The owner's profile: settings the numbers depend on, such as body weight."""

from __future__ import annotations

from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from trainer.storage.database import connect, write_transaction
from trainer.storage.profile import Profile, read_profile, save_profile

router = APIRouter(prefix="/api")


class ProfileIn(BaseModel):
    """The whole profile, as the owner last set it."""

    bodyweight_kg: Annotated[float, Field(gt=0, le=500)] | None = None


def _database(request: Request) -> str:
    return str(request.app.state.settings.database)


@router.get("/profile")
def get_profile(request: Request) -> Profile:
    """The owner's profile; empty until first saved."""
    with closing(connect(_database(request))) as conn:
        return read_profile(conn)


@router.put("/profile")
def put_profile(request: Request, body: ProfileIn) -> Profile:
    """Replace the profile (idempotent, so the offline queue can replay it)."""
    with closing(connect(_database(request))) as conn:
        with write_transaction(conn):
            save_profile(conn, Profile(body.bodyweight_kg))
        return read_profile(conn)
