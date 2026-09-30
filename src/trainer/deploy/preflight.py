"""Host checks the root installer runs before it changes anything.

Configuration validation (``config.py``) can only judge values; this module
looks at the real host. Every rule fails closed, so a typo or a pre-existing
account or directory is refused rather than taken over:

* the service account, if it already exists, is a dedicated system account:
  uid 1-999, a same-named primary group, home ``/nonexistent`` and a nologin
  shell; a same-named group without that user is refused;
* the data directory, if it exists, is a real directory already owned by that
  account; its existing ancestors are real directories owned by root or by the
  admin running the installer, and writable by nobody else;
* the code prefix, if it exists, is a real root-owned directory writable by
  nobody else, and is either empty or already marked as ours; its existing
  ancestors are root-owned and writable by nobody else.
"""

from __future__ import annotations

import grp
import os
import pwd
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import PurePosixPath

    from trainer.deploy.config import DeployConfig

SYSTEM_UID_MAX = 999
SERVICE_HOME = "/nonexistent"
NOLOGIN_SHELLS = frozenset({"/usr/sbin/nologin", "/sbin/nologin", "/usr/bin/false", "/bin/false"})
PREFIX_MARKER = ".hermes-trainer"
WRITABLE_BY_OTHERS = stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True)
class Account:
    """The fields of a passwd entry the checks need."""

    uid: int
    gid: int
    home: str
    login_shell: str


@dataclass(frozen=True)
class Entry:
    """``lstat`` of a path: owner and mode (including the file-type bits)."""

    uid: int
    mode: int


class Host(Protocol):
    """Read-only view of the machine being installed on."""

    def account(self, name: str) -> Account | None:
        """The named user, or ``None``."""
        ...

    def group_name(self, gid: int) -> str | None:
        """The name of a group id, or ``None``."""
        ...

    def group_exists(self, name: str) -> bool:
        """Whether a group of this name exists."""
        ...

    def entry(self, path: PurePosixPath) -> Entry | None:
        """``lstat`` of ``path`` without following symlinks, or ``None``."""
        ...

    def names(self, path: PurePosixPath) -> list[str]:
        """The entries of a directory."""
        ...


class SystemHost:
    """The real host, via ``pwd``, ``grp`` and ``os``."""

    def account(self, name: str) -> Account | None:
        """The named user, or ``None``."""
        try:
            entry = pwd.getpwnam(name)
        except KeyError:
            return None
        return Account(entry.pw_uid, entry.pw_gid, entry.pw_dir, entry.pw_shell)

    def group_name(self, gid: int) -> str | None:
        """The name of a group id, or ``None``."""
        try:
            return grp.getgrgid(gid).gr_name
        except KeyError:
            return None

    def group_exists(self, name: str) -> bool:
        """Whether a group of this name exists."""
        try:
            grp.getgrnam(name)
        except KeyError:
            return False
        return True

    def entry(self, path: PurePosixPath) -> Entry | None:
        """``lstat`` of ``path`` without following symlinks, or ``None``."""
        try:
            result = os.lstat(path)
        except FileNotFoundError:
            return None
        return Entry(result.st_uid, result.st_mode)

    def names(self, path: PurePosixPath) -> list[str]:
        """The entries of a directory."""
        return sorted(child.name for child in Path(path).iterdir())


def check_account(user: str, host: Host) -> tuple[list[str], int | None]:
    """Problems with an existing service account, and its uid if it exists."""
    account = host.account(user)
    if account is None:
        if host.group_exists(user):
            return [f"group {user!r} exists without a matching user; refusing to reuse it"], None
        return [], None
    problems: list[str] = []
    if not 0 < account.uid <= SYSTEM_UID_MAX:
        problems.append(f"account {user!r} has uid {account.uid}, not a system uid (1-999)")
    group = host.group_name(account.gid)
    if group != user:
        problems.append(f"account {user!r} has primary group {group!r}, not {user!r}")
    if account.home != SERVICE_HOME:
        problems.append(f"account {user!r} has home {account.home!r}, not {SERVICE_HOME!r}")
    if account.login_shell not in NOLOGIN_SHELLS:
        problems.append(f"account {user!r} has login shell {account.login_shell!r}")
    return problems, account.uid


def check_directory(path: PurePosixPath, owners: Collection[int], host: Host) -> list[str]:
    """Problems with an existing directory: kind, owner and write permissions."""
    entry = host.entry(path)
    if entry is None:
        return []
    if not stat.S_ISDIR(entry.mode):
        return [f"{path} is not a real directory (symlinks are refused)"]
    problems: list[str] = []
    if not owners:
        problems.append(f"{path} already exists but the service account does not")
    elif entry.uid not in owners:
        problems.append(f"{path} is owned by uid {entry.uid}, expected one of {sorted(owners)}")
    if entry.mode & WRITABLE_BY_OTHERS:
        problems.append(f"{path} is writable by its group or others")
    return problems


def check_ancestors(path: PurePosixPath, owners: Collection[int], host: Host) -> list[str]:
    """Every existing ancestor, from ``/`` down, must be a safe directory."""
    return [
        problem
        for ancestor in reversed(path.parents)
        for problem in check_directory(ancestor, owners, host)
    ]


def check_prefix(prefix: PurePosixPath, host: Host) -> list[str]:
    """The code prefix is root-owned, private, and empty or already ours."""
    problems = check_directory(prefix, {0}, host)
    if problems or host.entry(prefix) is None:
        return problems
    names = host.names(prefix)
    if names and PREFIX_MARKER not in names:
        return [f"{prefix} is not empty and not a hermes-trainer prefix; refusing to use it"]
    return []


def preflight(config: DeployConfig, host: Host, admin_uid: int) -> list[str]:
    """Every reason the installer must not proceed; empty when it may."""
    problems, service_uid = check_account(config.user, host)
    data_owners = set() if service_uid is None else {service_uid}
    problems += check_ancestors(config.data_dir, {0, admin_uid}, host)
    problems += check_directory(config.data_dir, data_owners, host)
    problems += check_ancestors(config.prefix, {0}, host)
    problems += check_prefix(config.prefix, host)
    return problems
