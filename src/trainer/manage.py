"""``python -m trainer.manage``: database administration commands."""

from __future__ import annotations

import argparse
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from trainer.services.import_v1 import import_v1
from trainer.storage.database import connect, migrate


def _migrate(args: argparse.Namespace) -> int:
    with closing(connect(args.database)) as conn:
        version = migrate(conn)
    sys.stdout.write(f"schema at v{version}\n")
    return 0


def _import_v1(args: argparse.Namespace) -> int:
    if not args.source.is_file():
        sys.stderr.write(f"v1 database not found: {args.source}\n")
        return 1
    with closing(connect(args.source)) as source, closing(connect(args.database)) as target:
        migrate(target)
        summary = import_v1(source, target)
    counts = ", ".join(
        f"{count} {kind.replace('_', ' ')}" for kind, count in asdict(summary).items()
    )
    sys.stdout.write(f"imported from v1: {counts}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m trainer.manage", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    up = commands.add_parser("migrate", help="create or upgrade the database schema")
    up.add_argument("--database", required=True)
    up.set_defaults(handler=_migrate)
    v1 = commands.add_parser("import-v1", help="(re)import history from a v1 gym database copy")
    v1.add_argument("--source", type=Path, required=True)
    v1.add_argument("--database", required=True)
    v1.set_defaults(handler=_import_v1)
    args = parser.parse_args(argv)
    status: int = args.handler(args)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
