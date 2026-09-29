"""Render the systemd units and the root installer's variables from a config."""

from __future__ import annotations

import shlex
from importlib.resources import files
from string import Template
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from trainer.deploy.config import DeployConfig

UNITS = ("trainer-api.service", "trainer-backup.service", "trainer-backup.timer")


def substitutions(config: DeployConfig) -> dict[str, str]:
    """Template variables available to every unit."""
    return {
        "user": config.user,
        "data_dir": str(config.data_dir),
        "prefix": str(config.prefix),
        "bind_host": config.bind_host,
        "bind_port": str(config.bind_port),
        "backup_keep": str(config.backup_keep),
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
    """Shell-quoted variables for ``deploy/install.sh`` and ``tailscale-serve.sh``."""
    variables = {
        "TRAINER_USER": config.user,
        "TRAINER_DATA_DIR": str(config.data_dir),
        "TRAINER_PREFIX": str(config.prefix),
        "TRAINER_UPSTREAM": config.upstream,
    }
    return "".join(f"{key}={shlex.quote(value)}\n" for key, value in variables.items())


def write_bundle(config: DeployConfig, out: Path) -> list[Path]:
    """Write ``systemd/<unit>`` files and ``install.env`` under ``out``."""
    written: list[Path] = []
    (out / "systemd").mkdir(parents=True, exist_ok=True)
    for unit, content in render_units(config).items():
        path = out / "systemd" / unit
        path.write_bytes(content.encode())
        written.append(path)
    env_path = out / "install.env"
    env_path.write_bytes(install_env(config).encode())
    written.append(env_path)
    return written
