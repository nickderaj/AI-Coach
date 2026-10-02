"""The server's VAPID key pair on disk, in two root-only files.

The private key (``push.env``, for the sender) is the source of truth. The
public file (``push-public.env``, for the API) is derived from it and written
again whenever it does not match, so a run cut short between the two files
(say, mid-rotation) is put right by the next one.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING

from trainer.services.webpush import VapidKey

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PRIVATE_FILE = "push.env"
PUBLIC_FILE = "push-public.env"
PRIVATE_NAME = "TRAINER_VAPID_PRIVATE_KEY"
PUBLIC_NAME = "TRAINER_VAPID_PUBLIC_KEY"


class KeysError(RuntimeError):
    """The private key file is there but holds no key."""


class KeysResult(StrEnum):
    """What ``write_keys`` did."""

    MADE = "made a new VAPID key pair"
    KEPT = "kept the existing VAPID key pair"
    REPAIRED = "kept the private key and wrote its public key again"


def write_keys(
    directory: Path, *, rotate: bool, generate: Callable[[], VapidKey] = VapidKey.generate
) -> KeysResult:
    """Make the pair if there is none (or ``rotate``), and make the public file match.

    Raises:
        KeysError: if the private file holds no key (it is not overwritten).
        ValueError: if its key is not a P-256 private key.
    """
    private_path, public_path = directory / PRIVATE_FILE, directory / PUBLIC_FILE
    key = None if rotate else _read_private(private_path)
    made = key is None
    if key is None:
        key = generate()
        _write(private_path, f"{PRIVATE_NAME}={key.text}\n")
    public = f"{PUBLIC_NAME}={key.public_text}\n"
    current = public_path.read_bytes().decode() if public_path.exists() else None
    if current != public:
        _write(public_path, public)
    if made:
        return KeysResult.MADE
    return KeysResult.KEPT if current == public else KeysResult.REPAIRED


def _read_private(path: Path) -> VapidKey | None:
    if not path.exists():
        return None
    for line in path.read_bytes().decode().splitlines():
        name, _, value = line.partition("=")
        if name == PRIVATE_NAME:
            return VapidKey.from_text(value.strip())
    message = f"{path} holds no {PRIVATE_NAME}; move it away to make a new pair"
    raise KeysError(message)


def _write(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` at once, readable by its owner only."""
    staged = path.with_name(f".{path.name}.new")
    # Created owner-only: the umask can only narrow this mode, never widen it.
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, text.encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    staged.replace(path)
