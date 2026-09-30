"""Parse and validate the deployment's host-specific settings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import PurePosixPath

KEYS = (
    "TRAINER_USER",
    "TRAINER_DATA_DIR",
    "TRAINER_PREFIX",
    "TRAINER_BIND_HOST",
    "TRAINER_BIND_PORT",
    "TRAINER_BACKUP_KEEP",
    "TRAINER_OWNER_LOGIN",
)
USER_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
# A Tailscale login (e.g. an email address). No "%": systemd expands it in units.
LOGIN = re.compile(r"^[A-Za-z0-9._+@-]{1,254}$")
SAFE_PATH = re.compile(r"^(?:/[A-Za-z0-9._-]+)+$")
# Dedicated locations only. The two sets are disjoint, so the service-writable
# data directory and the root-owned code prefix can never be equal or nested.
DATA_ROOTS = ("/srv", "/var/lib", "/mnt", "/media")
PREFIX_ROOTS = ("/opt", "/usr/local")
RESERVED_USERS = frozenset({"root", "nobody"})
MIN_PORT = 1024
MAX_PORT = 65535
MAX_BACKUPS = 365


class ConfigError(ValueError):
    """The deployment configuration is missing, malformed or unsafe."""


@dataclass(frozen=True)
class DeployConfig:
    """Validated deployment settings."""

    user: str
    data_dir: PurePosixPath
    prefix: PurePosixPath
    bind_host: str
    bind_port: int
    backup_keep: int
    owner_login: str

    @property
    def upstream(self) -> str:
        """``host:port`` for the API, with IPv6 hosts bracketed for URLs."""
        host = f"[{self.bind_host}]" if ":" in self.bind_host else self.bind_host
        return f"{host}:{self.bind_port}"


def parse_env(text: str) -> dict[str, str]:
    """Read ``KEY=VALUE`` lines; blank lines and ``#`` comments are ignored.

    Raises:
        ConfigError: on a line without ``=`` or a key set twice.
    """
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator:
            message = f"line {number}: expected KEY=VALUE"
            raise ConfigError(message)
        if key in values:
            message = f"line {number}: {key} is set twice"
            raise ConfigError(message)
        values[key] = value.strip()
    return values


def load(text: str) -> DeployConfig:
    """Validate a ``local.env`` document into a :class:`DeployConfig`.

    Raises:
        ConfigError: if a key is missing or unknown, or a value is unsafe.
    """
    values = parse_env(text)
    missing = [key for key in KEYS if key not in values]
    if missing:
        message = f"missing {', '.join(missing)}"
        raise ConfigError(message)
    unknown = sorted(set(values) - set(KEYS))
    if unknown:
        message = f"unknown {', '.join(unknown)}"
        raise ConfigError(message)
    return DeployConfig(
        user=_user(values["TRAINER_USER"]),
        data_dir=_path("TRAINER_DATA_DIR", values["TRAINER_DATA_DIR"], DATA_ROOTS),
        prefix=_path("TRAINER_PREFIX", values["TRAINER_PREFIX"], PREFIX_ROOTS),
        bind_host=_loopback(values["TRAINER_BIND_HOST"]),
        bind_port=_integer("TRAINER_BIND_PORT", values["TRAINER_BIND_PORT"], MIN_PORT, MAX_PORT),
        backup_keep=_integer("TRAINER_BACKUP_KEEP", values["TRAINER_BACKUP_KEEP"], 1, MAX_BACKUPS),
        owner_login=_login(values["TRAINER_OWNER_LOGIN"]),
    )


def to_env(config: DeployConfig) -> str:
    """Serialise a validated config back to canonical ``local.env`` form."""
    values = {
        "TRAINER_USER": config.user,
        "TRAINER_DATA_DIR": str(config.data_dir),
        "TRAINER_PREFIX": str(config.prefix),
        "TRAINER_BIND_HOST": config.bind_host,
        "TRAINER_BIND_PORT": str(config.bind_port),
        "TRAINER_BACKUP_KEEP": str(config.backup_keep),
        "TRAINER_OWNER_LOGIN": config.owner_login,
    }
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _login(value: str) -> str:
    if not LOGIN.match(value):
        message = f"TRAINER_OWNER_LOGIN {value!r} is not a valid Tailscale login"
        raise ConfigError(message)
    return value


def _user(value: str) -> str:
    if not USER_NAME.match(value):
        message = f"TRAINER_USER {value!r} is not a valid system user name"
        raise ConfigError(message)
    if value in RESERVED_USERS:
        message = f"TRAINER_USER {value!r} is reserved; use a dedicated service account"
        raise ConfigError(message)
    return value


def _path(key: str, value: str, roots: tuple[str, ...]) -> PurePosixPath:
    if not SAFE_PATH.match(value) or {".", ".."} & set(value.split("/")):
        message = f"{key} {value!r} must be an absolute path of plain segments"
        raise ConfigError(message)
    path = PurePosixPath(value)
    if not any(path.parent.is_relative_to(root) for root in roots):
        message = f"{key} {value!r} must be a dedicated directory inside {' or '.join(roots)}"
        raise ConfigError(message)
    return path


def _is_loopback(value: str) -> bool:
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def _loopback(value: str) -> str:
    if not _is_loopback(value):
        message = (
            f"TRAINER_BIND_HOST {value!r} must be a loopback address; "
            "tailscale serve is the only way in"
        )
        raise ConfigError(message)
    return value


def _integer(key: str, value: str, low: int, high: int) -> int:
    if not value.isdigit() or not low <= int(value) <= high:
        message = f"{key} {value!r} must be an integer from {low} to {high}"
        raise ConfigError(message)
    return int(value)
