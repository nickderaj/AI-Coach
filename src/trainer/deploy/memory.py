"""Nightly commit of the coach's memory and skills to a private, local-only git repository.

Hermes writes what it learns to ``memories/`` and ``skills/`` in its home
directory as soon as it learns it (D11). Once a night this records those two
directories in a git repository beside the data, so every learned fact is a
diff the owner can review and revert. The repository is personal data: it
lives only on the host, has no remote, and refuses to be given one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# What is recorded, relative to the Hermes home. Sessions, logs and caches are not.
TRACKED = ("memories", "skills")
AUTHOR_NAME = "hermes-trainer"
AUTHOR_EMAIL = "hermes@localhost"
# Everything in the Hermes home is ignored except the tracked directories, so
# whole-tree commands see them alone (and a deleted one is recorded as deleted).
# Hermes's lock files ("USER.md.lock") sit beside what they guard; never record them.
EXCLUDE = "/*\n" + "".join(f"!/{name}/\n" for name in TRACKED) + "*.lock\n"
MESSAGE = "Learned since the last commit"


class MemoryRepoError(RuntimeError):
    """The memory repository is unusable or not private."""


def commit_memory(hermes_home: Path, repo: Path) -> str | None:
    """Commit any change to the tracked directories; return the new commit id.

    Creates ``repo`` (a bare repository whose work tree is ``hermes_home``) on
    first use. Returns ``None`` when nothing changed.

    Raises:
        MemoryRepoError: if there is no Hermes home, the repository has a
            remote, or git fails.
    """
    if not hermes_home.is_dir():
        message = f"{hermes_home} is not a directory"
        raise MemoryRepoError(message)
    _run("init", "--bare", "--initial-branch=main", str(repo))  # idempotent
    if _run(f"--git-dir={repo}", "remote").strip():
        message = f"{repo} has a remote; the coach's memory must stay on this host"
        raise MemoryRepoError(message)
    # git init's templates create info/; this only covers a git without them.
    (repo / "info").mkdir(exist_ok=True)  # pragma: no mutate  # why: info/ already exists
    (repo / "info" / "exclude").write_bytes(EXCLUDE.encode())
    work_tree = (f"--git-dir={repo}", f"--work-tree={hermes_home}")
    _run(*work_tree, "add", "--all")
    if not _run(*work_tree, "status", "--porcelain").strip():
        return None
    _run(*work_tree, "commit", "--message", MESSAGE)
    return _run(f"--git-dir={repo}", "rev-parse", "HEAD").strip()


def _run(*args: str) -> str:
    """Run git as the coach's author, with no user or system config; return its output."""
    git = shutil.which("git")
    if git is None:
        message = "git is not installed"
        raise MemoryRepoError(message)
    command = [git, "-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}", *args]
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    try:
        done = subprocess.run(  # noqa: S603  # why: fixed git argv; paths come from the unit, not users
            command, check=True, capture_output=True, text=True, env=environment
        )
    except subprocess.CalledProcessError as error:
        subcommand = next(arg for arg in args if not arg.startswith("-"))
        message = f"git {subcommand} failed: {error.stderr.strip()}"
        raise MemoryRepoError(message) from error
    return done.stdout
