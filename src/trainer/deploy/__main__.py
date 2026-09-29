"""``python -m trainer.deploy``: render the install bundle, or run a backup."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from trainer.deploy.backup import backup
from trainer.deploy.config import ConfigError, load
from trainer.deploy.render import write_bundle


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m trainer.deploy", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="validate local.env and render the bundle")
    render.add_argument("--env", type=Path, required=True)
    render.add_argument("--out", type=Path, required=True)
    nightly = commands.add_parser("backup", help="back up the database and rotate")
    nightly.add_argument("--data-dir", type=Path, required=True)
    nightly.add_argument("--keep", type=int, required=True)
    args = parser.parse_args(argv)

    if args.command == "render":
        try:
            config = load(args.env.read_bytes().decode())
        except ConfigError as error:
            sys.stderr.write(f"{args.env}: {error}\n")
            return 1
        for path in write_bundle(config, args.out):
            sys.stdout.write(f"rendered {path}\n")
        return 0

    written = backup(args.data_dir, args.keep, datetime.now(UTC))
    sys.stdout.write(f"backed up to {written}\n" if written else "no database yet; nothing to do\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
