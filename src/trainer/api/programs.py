"""Program endpoints: the active and proposed programs, and today's program day."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response

from trainer.services.programs import (
    MAX_ROW_ID,
    NoProposalError,
    ProgramError,
    ProgramIn,
    Programs,
    Today,
    accept_proposal,
    decline_proposal,
    programs,
    propose_program,
    today,
)
from trainer.storage.database import connect
from trainer.storage.programs import (
    Program,  # noqa: TC001  # why: FastAPI reads the annotation at runtime
)

router = APIRouter(prefix="/api")


def _database(request: Request) -> str:
    return str(request.app.state.settings.database)


@router.get("/programs")
def get_programs(request: Request) -> Programs:
    """The active program and its next day, and the proposed program."""
    with closing(connect(_database(request))) as conn:
        return programs(conn)


@router.put("/programs/proposal")
def put_proposal(request: Request, body: ProgramIn) -> Program:
    """Propose a program, replacing any earlier proposal; 422 if an exercise cannot be in it."""
    try:
        with closing(connect(_database(request))) as conn:
            return propose_program(conn, body, datetime.now(UTC))
    except ProgramError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/programs/proposal", status_code=204)
def delete_proposal(request: Request) -> Response:
    """Turn the proposal down."""
    with closing(connect(_database(request))) as conn:
        decline_proposal(conn)
    return Response(status_code=204)


@router.post("/programs/{program_id}/accept")
def accept(request: Request, program_id: Annotated[int, Path(ge=1, le=MAX_ROW_ID)]) -> Program:
    """Start the proposed program; 409 if it is no longer the proposal."""
    try:
        with closing(connect(_database(request))) as conn:
            return accept_proposal(conn, program_id, datetime.now(UTC))
    except NoProposalError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/today")
def get_today(request: Request) -> Today | None:
    """The active program's next day with its targets; null without an active program."""
    with closing(connect(_database(request))) as conn:
        return today(conn)
