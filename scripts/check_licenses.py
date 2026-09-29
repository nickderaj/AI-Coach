"""Fail when a runtime dependency is not under an allow-listed licence.

Reads ``uv export --no-dev --no-hashes --format requirements-txt`` on stdin and
checks each pinned package's installed metadata: the SPDX ``License-Expression``
when present, otherwise its ``License ::`` classifiers.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from importlib import metadata
from typing import Protocol

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


def licenses(package: LicenseMetadata) -> set[str]:
    """SPDX identifiers a package declares (empty when it declares none we understand)."""
    expression = package.get("License-Expression")
    if expression:
        return {part for part in SPDX_SEPARATOR.split(expression) if part.strip()}
    return {
        CLASSIFIER_SPDX.get(classifier, classifier)
        for classifier in package.get_all("Classifier") or []
        if classifier.startswith("License ::")
    }


def violations(names: list[str], lookup: MetadataLookup | None = None) -> list[str]:
    """One message per package whose licence is missing or not allow-listed."""
    lookup = lookup or metadata.metadata
    found: list[str] = []
    for name in names:
        declared = licenses(lookup(name))
        if not declared:
            found.append(f"{name}: declares no recognisable licence")
        elif not declared <= ALLOWED:
            found.append(f"{name}: {', '.join(sorted(declared - ALLOWED))} is not allow-listed")
    return found


def main() -> int:
    """Entry point: pipe the runtime requirements export into stdin."""
    names = pinned_packages(sys.stdin.read())
    if not names:
        sys.stderr.write("licenses: no pinned packages on stdin\n")
        return 1
    problems = violations(names)
    for problem in problems:
        sys.stderr.write(f"licenses: {problem}\n")
    if problems:
        return 1
    sys.stdout.write(f"licenses: ok ({len(names)} runtime packages)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
