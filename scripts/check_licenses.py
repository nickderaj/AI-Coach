"""Fail when a runtime dependency is not under an allow-listed licence.

Python (default): reads ``uv export --no-dev --no-hashes --format
requirements-txt`` on stdin and checks each pinned package's installed metadata,
the SPDX ``License-Expression`` when present, otherwise its ``License ::``
classifiers.

Web (``--pnpm``): reads ``pnpm licenses list --prod --json`` on stdin, which
groups production packages by their declared licence.

Both use the same allow-list, so the product ships under one licence policy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from importlib import metadata
from typing import Any, Protocol

ALLOWED = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MIT",
        "PSF-2.0",
    }
)
CLASSIFIER_SPDX = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
}
PINNED = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==")
SPDX_SEPARATOR = re.compile(r"\s+(?:OR|AND)\s+|[()]")


class LicenseMetadata(Protocol):
    """The two metadata accessors the check needs (satisfied by ``PackageMetadata``)."""

    def get(self, name: str, /) -> str | None:
        """First value of a header, if present."""
        ...

    def get_all(self, name: str, /) -> list[str] | None:
        """Every value of a header, if present."""
        ...


type MetadataLookup = Callable[[str], LicenseMetadata]


def pinned_packages(requirements: str) -> list[str]:
    """Package names from a pinned requirements export."""
    return [
        match.group("name") for line in requirements.splitlines() if (match := PINNED.match(line))
    ]


def spdx_identifiers(expression: str) -> set[str]:
    """Split an SPDX expression such as ``(MIT OR Apache-2.0)`` into identifiers."""
    return {part.strip() for part in SPDX_SEPARATOR.split(expression) if part.strip()}


def licenses(package: LicenseMetadata) -> set[str]:
    """SPDX identifiers a package declares (empty when it declares none we understand)."""
    expression = package.get("License-Expression")
    if expression:
        return spdx_identifiers(expression)
    return {
        CLASSIFIER_SPDX.get(classifier, classifier)
        for classifier in package.get_all("Classifier") or []
        if classifier.startswith("License ::")
    }


def violation(name: str, declared: set[str]) -> str | None:
    """Describe why ``declared`` is unacceptable, or ``None`` when it is allowed."""
    if not declared:
        return f"{name}: declares no recognisable licence"
    if not declared <= ALLOWED:
        return f"{name}: {', '.join(sorted(declared - ALLOWED))} is not allow-listed"
    return None


def python_packages(text: str, lookup: MetadataLookup | None = None) -> tuple[list[str], list[str]]:
    """(package names, violations) for a pinned requirements export."""
    lookup = lookup or metadata.metadata
    names = pinned_packages(text)
    found = [problem for name in names if (problem := violation(name, licenses(lookup(name))))]
    return names, found


def pnpm_packages(text: str) -> tuple[list[str], list[str]]:
    """(package names, violations) for a ``pnpm licenses list --json`` report."""
    report: dict[str, list[dict[str, Any]]] = json.loads(text) if text.strip() else {}
    names: list[str] = []
    found: list[str] = []
    for expression, packages in sorted(report.items()):
        for package in packages:
            name = str(package["name"])
            names.append(name)
            if problem := violation(name, spdx_identifiers(expression)):
                found.append(problem)
    return names, found


def main(argv: list[str] | None = None) -> int:
    """Entry point: pipe the dependency listing into stdin."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pnpm", action="store_true", help="stdin is a pnpm licences report")
    args = parser.parse_args(argv)
    text = sys.stdin.read()
    names, problems = pnpm_packages(text) if args.pnpm else python_packages(text)
    if not names:
        sys.stderr.write("licenses: no packages on stdin\n")
        return 1
    for problem in problems:
        sys.stderr.write(f"licenses: {problem}\n")
    if problems:
        return 1
    sys.stdout.write(f"licenses: ok ({len(names)} runtime packages)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
