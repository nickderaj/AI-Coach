"""``python -m trainer.manage``: database administration commands."""

from __future__ import annotations

import argparse
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from trainer.services.import_v1 import (
    Changes,
    ImportPreview,
    ImportSummary,
    import_v1,
    preview_import,
)
from trainer.services.seed import (
    common_exercises,
    describe,
    missing_exercises,
    seed_exercises,
)
from trainer.storage.database import connect, connect_readonly, migrate


def _migrate(args: argparse.Namespace) -> int:
    with closing(connect(args.database)) as conn:
        version = migrate(conn)
    sys.stdout.write(f"schema at v{version}\n")
    return 0


def _import_v1(args: argparse.Namespace) -> int:
    if not args.source.is_file():
        sys.stderr.write(f"v1 database not found: {args.source}\n")
        return 1
    database = Path(args.database)
    if database.exists() and args.source.samefile(database):
        sys.stderr.write(f"refusing to import {args.source} into itself\n")
        return 1
    if args.dry_run:
        return _dry_run(args.source, database)
    with (
        closing(connect_readonly(args.source)) as source,
        closing(connect(database)) as target,
    ):
        migrate(target)
        summary = import_v1(source, target)
    sys.stdout.write(f"imported from v1: {_counts(summary)}\n")
    return 0


def _dry_run(source_path: Path, database: Path) -> int:
    if not database.is_file():
        sys.stderr.write(f"no database to compare with: {database}\n")
        return 1
    with (
        closing(connect_readonly(source_path)) as source,
        closing(connect_readonly(database)) as target,
    ):
        _report(preview_import(source, target))
    return 0


def _counts(summary: ImportSummary) -> str:
    return ", ".join(f"{count} {kind.replace('_', ' ')}" for kind, count in asdict(summary).items())


def _report(preview: ImportPreview) -> None:
    """What a dry run of the v1 import found, against what the last import wrote."""
    lines = [
        f"would import from v1: {_counts(preview.summary)}",
        "changes against the last import (nothing written):",
    ]
    kinds: dict[str, Changes] = {
        "workouts": preview.workouts,
        "sets": preview.sets,
        "body metrics": preview.body_metrics,
        "cardio sessions": preview.cardio_sessions,
    }
    for kind, changes in kinds.items():
        lines.append(f"  {kind}: {len(changes.added)} added, {len(changes.removed)} removed")
        lines += [f"    + {line}" for line in changes.added]
        lines += [f"    - {line}" for line in changes.removed]
    lines.append(f"  exercises new to the catalogue: {', '.join(preview.new_exercises) or 'none'}")
    sys.stdout.write("".join(f"{line}\n" for line in lines))


def _seed_exercises(args: argparse.Namespace) -> int:
    with closing(connect(args.database)) as conn:
        migrate(conn)
        if args.dry_run:
            exercises = missing_exercises(conn, common_exercises())
        else:
            exercises = seed_exercises(conn, common_exercises())
    verb = "would add" if args.dry_run else "added"
    sys.stdout.write(f"{verb} {len(exercises)} common exercises\n")
    for exercise in exercises:
        sys.stdout.write(f"  {describe(exercise)}\n")
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
    v1.add_argument(
        "--dry-run", action="store_true", help="show what would change, writing nothing"
    )
    v1.set_defaults(handler=_import_v1)
    seed = commands.add_parser(
        "seed-exercises", help="add common exercises the catalogue does not have yet"
    )
    seed.add_argument("--database", required=True)
    seed.add_argument("--dry-run", action="store_true", help="list them without adding")
    seed.set_defaults(handler=_seed_exercises)
    args = parser.parse_args(argv)
    status: int = args.handler(args)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
