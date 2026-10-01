"""``python -m trainer.deploy``: render the bundle, back up, or commit the coach's memory."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from trainer.deploy.backup import backup
from trainer.deploy.config import ConfigError, DeployConfig, load
from trainer.deploy.memory import MemoryRepoError, commit_memory
from trainer.deploy.preflight import SystemHost, preflight
from trainer.deploy.render import write_bundle


def _load(env: Path) -> DeployConfig | None:
    try:
        return load(env.read_bytes().decode())
    except ConfigError as error:
        sys.stderr.write(f"{env}: {error}\n")
        return None


def _render(args: argparse.Namespace) -> int:
    config = _load(args.env)
    if config is None:
        return 1
    for path in write_bundle(config, args.out):
        sys.stdout.write(f"rendered {path}\n")
    return 0


def _preflight(args: argparse.Namespace) -> int:
    config = _load(args.env)
    if config is None:
        return 1
    problems = preflight(config, SystemHost(), args.admin_uid)
    for problem in problems:
        sys.stderr.write(f"preflight: {problem}\n")
    return 1 if problems else 0


def _backup(args: argparse.Namespace) -> int:
    written = backup(args.data_dir, args.keep, datetime.now(UTC))
    sys.stdout.write(f"backed up to {written}\n" if written else "no database yet; nothing to do\n")
    return 0


def _memory_commit(args: argparse.Namespace) -> int:
    try:
        commit = commit_memory(args.hermes_home, args.repo)
    except MemoryRepoError as error:
        sys.stderr.write(f"memory-commit: {error}\n")
        return 1
    sys.stdout.write(f"committed {commit}\n" if commit else "nothing learned; nothing to do\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m trainer.deploy", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="validate local.env and render the bundle")
    render.add_argument("--env", type=Path, required=True)
    render.add_argument("--out", type=Path, required=True)
    render.set_defaults(handler=_render)
    check = commands.add_parser("preflight", help="refuse unsafe host state before install")
    check.add_argument("--env", type=Path, required=True)
    check.add_argument("--admin-uid", type=int, required=True)
    check.set_defaults(handler=_preflight)
    nightly = commands.add_parser("backup", help="back up the database and rotate")
    nightly.add_argument("--data-dir", type=Path, required=True)
    nightly.add_argument("--keep", type=int, required=True)
    nightly.set_defaults(handler=_backup)
    learned = commands.add_parser(
        "memory-commit", help="commit the coach's memory and skills to its private repository"
    )
    learned.add_argument("--hermes-home", type=Path, required=True)
    learned.add_argument("--repo", type=Path, required=True)
    learned.set_defaults(handler=_memory_commit)
    args = parser.parse_args(argv)
    status: int = args.handler(args)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
