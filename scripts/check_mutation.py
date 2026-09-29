"""Fail when any mutant was not killed.

Reads ``mutmut results --all true`` output. Every mutant must be ``killed``;
an equivalent mutant is removed at the source (simplify the code) or marked
``# pragma: no mutate`` with a ``# why:`` justification, which the policy
checker enforces.
"""

from __future__ import annotations

import re
import sys

RESULT = re.compile(r"^\s*(?P<name>\S+__mutmut_\d+):\s*(?P<status>[\w ]+?)\s*$")


def failures(results: str) -> tuple[int, list[str]]:
    """Return (total mutants, lines describing every non-killed mutant)."""
    total = 0
    problems: list[str] = []
    for line in results.splitlines():
        match = RESULT.match(line)
        if match is None:
            continue
        total += 1
        if match.group("status") != "killed":
            problems.append(f"{match.group('name')}: {match.group('status')}")
    return total, problems


def main() -> int:
    """Entry point: pipe ``mutmut results --all true`` into stdin."""
    total, problems = failures(sys.stdin.read())
    if total == 0:
        sys.stderr.write("mutation: no mutant results found; did mutmut run?\n")
        return 1
    for problem in problems:
        sys.stderr.write(f"mutation: {problem} (inspect with `mutmut show <name>`)\n")
    if problems:
        return 1
    sys.stdout.write(f"mutation: ok ({total} mutants, all killed)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
