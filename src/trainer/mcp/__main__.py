"""``python -m trainer.mcp``: the coach's tool server, spoken over stdin and stdout.

Hermes starts it as a child process (``mcp_servers`` in ``hermes/config.yaml``).
It reads ``$TRAINER_DATA_DIR/trainer.db`` read-only and never writes it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from trainer.mcp.protocol import handle_line
from trainer.mcp.tools import tools
from trainer.storage.database import DATABASE_FILE

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import TextIO


def serve(lines: Iterable[str], out: TextIO, database: Path) -> None:
    """Answer each request line on ``out`` until the input ends."""
    available = tools(database)
    for line in lines:
        if not line.strip():
            continue
        response = handle_line(line, available)
        if response is not None:
            out.write(response + "\n")
            out.flush()


def main(environ: Mapping[str, str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    data_dir = (os.environ if environ is None else environ).get("TRAINER_DATA_DIR")
    if not data_dir:
        sys.stderr.write("trainer.mcp: TRAINER_DATA_DIR must be set\n")
        return 2
    serve(sys.stdin, sys.stdout, Path(data_dir) / DATABASE_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
