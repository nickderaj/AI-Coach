"""``python -m trainer.push``: push notices as they come due, or keep the VAPID keys.

``serve`` runs as ``trainer-push.service``, the only part of the app with a
route to the internet, and only to the push services. ``write-keys`` is run by
``deploy/push-secrets.sh``, as root, to make or check the server's key pair.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from trainer.push.keys import KeysError, write_keys
from trainer.services.notices import deliver
from trainer.services.webpush import VapidKey, WebPushSender
from trainer.storage.database import DATABASE_FILE, connect

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from trainer.services.notices import PushSender

logger = logging.getLogger("trainer.push")

SETTINGS = ("TRAINER_DATA_DIR", "TRAINER_VAPID_PRIVATE_KEY", "TRAINER_PUSH_CONTACT")
# How often the sender looks for notices that have come due.
POLL_S = 2.0


def push_round(database: Path, sender: PushSender, now: datetime) -> None:
    """Push what has come due by ``now``, and log what happened."""
    with closing(connect(database)) as conn:
        done = deliver(conn, sender, now)
    if done.delivered or done.failed or done.gone:
        logger.info(
            "pushed %d, failed %d, %d subscriptions ended", done.delivered, done.failed, done.gone
        )


def serve(
    database: Path,
    sender: PushSender,
    wait: Callable[[float], bool],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Push due notices every ``POLL_S`` seconds, until ``wait`` answers ``False``."""
    while True:
        push_round(database, sender, clock())
        if not wait(POLL_S):
            return


def _sleep(seconds: float) -> bool:
    time.sleep(seconds)
    return True


def _serve(env: Mapping[str, str], wait: Callable[[float], bool]) -> int:
    data_dir, key, contact = (env.get(name) for name in SETTINGS)
    if not data_dir or not key or not contact:
        sys.stderr.write(f"push: {', '.join(SETTINGS)} must be set\n")
        return 2
    sender = WebPushSender(VapidKey.from_text(key), contact)
    _log_to_stderr()
    serve(Path(data_dir) / DATABASE_FILE, sender, wait)
    return 0


def _log_to_stderr() -> None:
    """The app's messages, at INFO and above, go to stderr: the journal."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    app = logging.getLogger("trainer")
    app.addHandler(handler)
    app.setLevel(logging.INFO)


def _write_keys(directory: Path, *, rotate: bool) -> int:
    try:
        result = write_keys(directory, rotate=rotate)
    except (KeysError, ValueError) as error:
        sys.stderr.write(f"push: {error}\n")
        return 1
    sys.stdout.write(f"{result}\n")
    return 0


def main(
    argv: list[str] | None = None,
    env: Mapping[str, str] = os.environ,
    wait: Callable[[float], bool] = _sleep,
) -> int:
    """Entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m trainer.push", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="push notices as they come due (the systemd unit)")
    keys = commands.add_parser(
        "write-keys", help="make the VAPID key pair if there is none, and check its public file"
    )
    keys.add_argument("--dir", type=Path, required=True)
    keys.add_argument("--rotate", action="store_true", help="replace the pair with a new one")
    args = parser.parse_args(argv)
    if args.command == "write-keys":
        return _write_keys(args.dir, rotate=args.rotate)
    return _serve(env, wait)


if __name__ == "__main__":
    raise SystemExit(main())
