"""Enforce the coverage contract on a coverage.py JSON report.

* the whole package meets ``TOTAL_MINIMUM`` (lines + branches combined);
* every module meets ``MODULE_MINIMUM``;
* every function marked with a ``# coverage-critical`` line directly above its
  ``def`` (or its decorators) has no missing line and no missing branch.

Changed-line coverage is enforced separately by ``diff-cover``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOTAL_MINIMUM = 90.0
MODULE_MINIMUM = 85.0
CRITICAL_MARKER = "# coverage-critical"
DEF_LINE = re.compile(r"^\s*(?:async\s+)?def\s+\w+")
DECORATOR_OR_BLANK = re.compile(r"^\s*(?:@.*)?$")


@dataclass(frozen=True)
class CriticalFunction:
    """A function whose code must be fully covered."""

    path: str
    def_line: int


def critical_functions(root: Path, source_files: list[str]) -> list[CriticalFunction]:
    """Locate the ``def`` line that each ``# coverage-critical`` marker annotates.

    Raises:
        ValueError: if a marker is not followed by a function definition.
    """
    found: list[CriticalFunction] = []
    for relative in source_files:
        lines = (root / relative).read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.strip() != CRITICAL_MARKER:
                continue
            following = index + 1
            while following < len(lines) and not DEF_LINE.match(lines[following]):
                if not DECORATOR_OR_BLANK.match(lines[following]):
                    break
                following += 1
            if following >= len(lines) or not DEF_LINE.match(lines[following]):
                message = f"{relative}:{index + 1}: {CRITICAL_MARKER} is not above a function"
                raise ValueError(message)
            found.append(CriticalFunction(relative, following + 1))
    return found


def check(report: dict[str, Any], root: Path) -> list[str]:
    """Return one message per coverage-contract failure."""
    failures: list[str] = []
    total = float(report["totals"]["percent_covered"])
    if total < TOTAL_MINIMUM:
        failures.append(f"total coverage {total:.2f}% is below {TOTAL_MINIMUM}%")
    files: dict[str, Any] = report["files"]
    for relative, data in sorted(files.items()):
        percent = float(data["summary"]["percent_covered"])
        if percent < MODULE_MINIMUM:
            failures.append(f"{relative}: {percent:.2f}% is below {MODULE_MINIMUM}%")
    for critical in critical_functions(root, sorted(files)):
        functions: dict[str, Any] = files[critical.path]["functions"]
        match = next(
            (
                (name, data)
                for name, data in functions.items()
                if data.get("start_line") == critical.def_line
            ),
            None,
        )
        if match is None:
            failures.append(f"{critical.path}:{critical.def_line}: critical function not measured")
            continue
        name, data = match
        if data["missing_lines"] or data["missing_branches"]:
            failures.append(
                f"{critical.path}:{critical.def_line}: critical function {name} is missing "
                f"lines {data['missing_lines']} and branches {data['missing_branches']}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    """Entry point; exits non-zero when the contract is not met."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    if not report["meta"]["branch_coverage"]:
        sys.stderr.write("coverage: report was produced without branch coverage\n")
        return 1
    try:
        failures = check(report, args.root)
    except ValueError as error:
        failures = [str(error)]
    for failure in failures:
        sys.stderr.write(f"coverage: {failure}\n")
    if failures:
        return 1
    total = float(report["totals"]["percent_covered"])
    sys.stdout.write(f"coverage: ok ({total:.2f}%)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
