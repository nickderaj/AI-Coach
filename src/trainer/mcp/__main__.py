"""``python -m trainer.mcp``: the coach's tool server, spoken over stdin and stdout.

Hermes starts it as a child process (``mcp_servers`` in ``hermes/config.yaml``).
It reads ``$TRAINER_DATA_DIR/trainer.db`` read-only and never writes it. With
``TRAINER_API_URL`` and ``TRAINER_COACH_KEY`` (the gateway's key) it can also
propose a program, which the API saves.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from trainer.mcp.proposals import ProgramsApi
from trainer.mcp.protocol import handle_line
from trainer.mcp.tools import tools
from trainer.storage.database import DATABASE_FILE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import TextIO


def serve(
    lines: Iterable[str], out: TextIO, database: Path, programs_api: ProgramsApi | None = None
) -> None:
    """Answer each request line on ``out`` until the input ends."""
    available = tools(database, programs_api)
    for line in lines:
        if not line.strip():
            continue
        response = handle_line(line, available)
        if response is not None:
            out.write(response + "\n")
            out.flush()


def main(environ: Mapping[str, str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    env = os.environ if environ is None else environ
    data_dir = env.get("TRAINER_DATA_DIR")
    if not data_dir:
        sys.stderr.write("trainer.mcp: TRAINER_DATA_DIR must be set\n")
        return 2
    serve(sys.stdin, sys.stdout, Path(data_dir) / DATABASE_FILE, programs_api(env))
    return 0


def programs_api(env: Mapping[str, str]) -> ProgramsApi | None:
    """The API to propose programs through, if its address and the key are both set."""
    url, key = env.get("TRAINER_API_URL"), env.get("TRAINER_COACH_KEY")
    return ProgramsApi(url, key) if url and key else None


if __name__ == "__main__":
    raise SystemExit(main())
