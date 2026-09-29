"""Fail-closed repository policy checks with actionable diagnostics.

Rules that ruff, mypy, eslint and tsc cannot express live here: pinned
versions, pinned CI actions, justified suppressions, no skipped or focused
tests, no secrets or owner-specific paths, and Conventional Commit PR titles.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import override

ROOT = Path(__file__).resolve().parent.parent
SKIP_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "build",
        "mutants",
        "coverage",
        "htmlcov",
        ".hypothesis",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "__pycache__",
    }
)
# Lockfiles are machine-written and full of hashes; gitleaks scans them instead.
SECRET_SCAN_EXEMPT = frozenset({"uv.lock", "web/package-lock.json"})
OWNER_PATHS = ("/home/" + "nick", "/Users/" + "nick")
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{30,}\b"),
    "provider key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),
}
PYTHON_SUPPRESSION = re.compile(
    r"#\s*(?:noqa\b|type:\s*ignore\b|pragma:\s*no\s*(?:cover|mutate)\b)"
)
JUSTIFICATION = re.compile(r"#\s*why:\s*\S")
PYTHON_FORBIDDEN = {
    "skipped or expected-failure test": re.compile(r"\bpytest\.mark\.(?:skip|skipif|xfail)\b"),
    "debugger breakpoint": re.compile(r"\bbreakpoint\(\)|\bpdb\.set_trace\("),
}
TS_FORBIDDEN = {
    "focused or skipped test": re.compile(r"\b(?:describe|it|test)\.(?:only|skip|todo)\s*\("),
    "TypeScript checker suppression": re.compile(r"@ts-(?:ignore|nocheck)\b"),
}
ESLINT_DIRECTIVE = re.compile(r"eslint-disable(?:-next-line|-line)?\b(?P<rest>.*)")
EXACT_PYTHON_REQUIREMENT = re.compile(r"^[A-Za-z0-9._\[\]-]+==[A-Za-z0-9.+-]+$")
EXACT_NPM_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
PINNED_ACTION = re.compile(r"@[0-9a-f]{40}$")
USES = re.compile(r"\buses:\s*([^\s#]+)")
GO_TOOL = re.compile(r"\bgo\s+(?:run|install)\s+[^\s@]+@(\S+)")
PR_TITLE = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|test)"
    r"(?:\([a-z0-9-]+\))?!?: [a-z0-9`].{0,70}$"
)


@dataclass(frozen=True, order=True)
class Violation:
    """One policy failure, printed as ``path[:line]: message``."""

    path: str
    line: int
    message: str

    @override
    def __str__(self) -> str:
        """Format for the terminal."""
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.message}"


type Check = Callable[[str, str], list[Violation]]


def repository_paths(root: Path) -> list[Path]:
    """Every path under ``root`` that could be committed.

    In a git work tree that is tracked plus untracked-but-not-ignored files, so
    build output such as ``coverage.xml`` is never checked. Outside git (unit
    tests), everything not under a well-known generated directory.
    """
    if (root / ".git").exists():
        git = shutil.which("git")
        if git is None:
            message = "git is required to list repository files"
            raise RuntimeError(message)
        listed = subprocess.run(  # noqa: S603  # why: fixed argv, no external input
            [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        candidates = (root / name for name in listed.split("\0") if name)
        return sorted(path for path in candidates if path.exists() or path.is_symlink())
    return sorted(
        path
        for path in root.rglob("*")
        if not SKIP_PARTS.intersection(path.relative_to(root).parts)
    )


def check_text(relative: str, text: str) -> list[Violation]:
    """Checks that apply to any text file."""
    found: list[Violation] = []
    if any(owner in text for owner in OWNER_PATHS):
        found.append(Violation(relative, 0, "owner-specific absolute path"))
    if relative not in SECRET_SCAN_EXEMPT:
        found.extend(
            Violation(relative, 0, f"likely {label}")
            for label, pattern in SECRET_PATTERNS.items()
            if pattern.search(text)
        )
    return found


def check_python(relative: str, text: str) -> list[Violation]:
    """Justified suppressions only; no skipped tests or breakpoints."""
    found: list[Violation] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        if PYTHON_SUPPRESSION.search(line):
            previous = lines[number - 2] if number > 1 else ""
            if not (JUSTIFICATION.search(line) or JUSTIFICATION.search(previous)):
                found.append(
                    Violation(relative, number, "suppression needs a '# why: ...' justification")
                )
        found.extend(
            Violation(relative, number, f"{label} is prohibited")
            for label, pattern in PYTHON_FORBIDDEN.items()
            if pattern.search(line)
        )
    return found


def check_typescript(relative: str, text: str) -> list[Violation]:
    """No focused/skipped tests, no tsc suppressions, described eslint directives."""
    found: list[Violation] = []
    for number, line in enumerate(text.splitlines(), 1):
        found.extend(
            Violation(relative, number, f"{label} is prohibited")
            for label, pattern in TS_FORBIDDEN.items()
            if pattern.search(line)
        )
        directive = ESLINT_DIRECTIVE.search(line)
        if directive and " -- " not in directive.group("rest"):
            found.append(
                Violation(relative, number, "eslint directive needs a '-- reason' description")
            )
    return found


def check_pyproject(relative: str, text: str) -> list[Violation]:
    """Every Python requirement is pinned to one exact version."""
    document = tomllib.loads(text)
    requirements: list[str] = list(document.get("project", {}).get("dependencies", []))
    requirements += document.get("build-system", {}).get("requires", [])
    for group in document.get("dependency-groups", {}).values():
        requirements += [item for item in group if isinstance(item, str)]
    return [
        Violation(relative, 0, f"requirement must be pinned with '==': {requirement}")
        for requirement in requirements
        if not EXACT_PYTHON_REQUIREMENT.match(requirement.replace(" ", ""))
    ]


def check_package_json(relative: str, text: str) -> list[Violation]:
    """Every npm dependency is pinned to one exact version."""
    document = json.loads(text)
    return [
        Violation(relative, 0, f"{section}.{name} must be an exact version, not {version!r}")
        for section in ("dependencies", "devDependencies", "optionalDependencies")
        for name, version in document.get(section, {}).items()
        if not EXACT_NPM_VERSION.match(version)
    ]


def check_workflow(relative: str, text: str) -> list[Violation]:
    """Actions and Go tools are pinned to full commit SHAs."""
    found: list[Violation] = []
    for number, line in enumerate(text.splitlines(), 1):
        uses = USES.search(line)
        if uses and not uses.group(1).startswith("./") and not PINNED_ACTION.search(uses.group(1)):
            found.append(Violation(relative, number, "action must be pinned to a full commit SHA"))
        go_tool = GO_TOOL.search(line)
        if go_tool and not re.fullmatch(r"[0-9a-f]{40}", go_tool.group(1)):
            found.append(Violation(relative, number, "Go tool must be pinned to a full commit SHA"))
    return found


SUFFIX_CHECKS: dict[str, Check] = {
    ".py": check_python,
    ".ts": check_typescript,
    ".tsx": check_typescript,
}


def checks_for(relative: str) -> list[Check]:
    """Every content check that applies to the file at ``relative``."""
    path = PurePosixPath(relative)
    checks: list[Check] = [check_text]
    if path.suffix in SUFFIX_CHECKS:
        checks.append(SUFFIX_CHECKS[path.suffix])
    if relative == "pyproject.toml":
        checks.append(check_pyproject)
    elif path.name == "package.json":
        checks.append(check_package_json)
    elif relative.startswith(".github/workflows/"):
        checks.append(check_workflow)
    return checks


def check_file(root: Path, path: Path) -> list[Violation]:
    """Run every applicable check on one repository path."""
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        return [Violation(relative, 0, "repository symlinks are prohibited")]
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return [violation for check in checks_for(relative) for violation in check(relative, text)]


def check_pr_title(title: str) -> list[Violation]:
    """Squash-merge titles become commit subjects, so they follow Conventional Commits."""
    if PR_TITLE.match(title):
        return []
    return [
        Violation(
            "pull request title",
            0,
            f"{title!r} is not '<type>(<scope>)?: <lower-case summary>' within 80 characters",
        )
    ]


def run(root: Path, pr_title: str | None) -> list[Violation]:
    """Collect every violation under ``root`` (and in the PR title, if given)."""
    found = [violation for path in repository_paths(root) for violation in check_file(root, path)]
    if pr_title is not None:
        found += check_pr_title(pr_title)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    """Entry point; exits non-zero on any violation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-title", help="also validate a pull request title")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    violations = run(args.root, args.pr_title)
    for violation in violations:
        sys.stderr.write(f"policy: {violation}\n")
    if violations:
        return 1
    sys.stdout.write("policy: ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
