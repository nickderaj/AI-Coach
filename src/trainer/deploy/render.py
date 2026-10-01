"""Render the systemd units and the root installer's variables from a config."""

from __future__ import annotations

import shlex
from importlib.resources import files
from string import Template
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from trainer.deploy.config import DeployConfig

from trainer.deploy.config import SECRETS_DIR, to_env

UNITS = (
    "trainer-api.service",
    "trainer-backup.service",
    "trainer-backup.timer",
    "trainer-coach.service",
    "trainer-memory.service",
    "trainer-memory.timer",
)


def substitutions(config: DeployConfig) -> dict[str, str]:
    """Template variables available to every unit."""
    return {
        "user": config.user,
        "data_dir": str(config.data_dir),
        "prefix": str(config.prefix),
        "bind_host": config.bind_host,
        "bind_port": str(config.bind_port),
        "backup_keep": str(config.backup_keep),
        "owner_login": config.owner_login,
        "hermes_port": str(config.hermes_port),
        "hermes_upstream": config.hermes_upstream,
        "model_url": config.model_url,
        "model": config.model,
        "hermes_home": str(config.hermes_home),
        "memory_repo": str(config.memory_repo),
        "secrets_dir": str(SECRETS_DIR),
    }


def render_units(config: DeployConfig) -> dict[str, str]:
    """Unit file name to rendered content; a missing variable is an error."""
    templates = files() / "templates"
    values = substitutions(config)
    return {
        unit: Template((templates / f"{unit}.in").read_bytes().decode()).substitute(values)
        for unit in UNITS
    }


def install_env(config: DeployConfig) -> str:
    """Shell-quoted variables for the root scripts in ``deploy/``."""
    variables = {
        "TRAINER_USER": config.user,
        "TRAINER_DATA_DIR": str(config.data_dir),
        "TRAINER_PREFIX": str(config.prefix),
        "TRAINER_UPSTREAM": config.upstream,
        "TRAINER_HERMES_UPSTREAM": config.hermes_upstream,
        "TRAINER_HERMES_HOME": str(config.hermes_home),
        "TRAINER_MEMORY_REPO": str(config.memory_repo),
        "TRAINER_SECRETS_DIR": str(SECRETS_DIR),
    }
    return "".join(f"{key}={shlex.quote(value)}\n" for key, value in variables.items())


def write_bundle(config: DeployConfig, out: Path) -> list[Path]:
    """Write ``systemd/<unit>``, ``install.env`` and ``config.env`` under ``out``."""
    written: list[Path] = []
    (out / "systemd").mkdir(parents=True, exist_ok=True)
    for unit, content in render_units(config).items():
        path = out / "systemd" / unit
        path.write_bytes(content.encode())
        written.append(path)
    env_path = out / "install.env"
    env_path.write_bytes(install_env(config).encode())
    written.append(env_path)
    config_path = out / "config.env"
    config_path.write_bytes(to_env(config).encode())
    written.append(config_path)
    return written
