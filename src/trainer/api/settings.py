"""Runtime settings for the API, read from the service environment."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from trainer.storage.database import DATABASE_FILE

if TYPE_CHECKING:
    from collections.abc import Mapping


class SettingsError(RuntimeError):
    """A required setting is missing from the environment."""


@dataclass(frozen=True)
class CoachSettings:
    """Where the coach's Hermes gateway listens, and the key its API checks."""

    url: str
    key: str = field(repr=False)


@dataclass(frozen=True)
class Settings:
    """Where the data lives, what to serve, and who may use it."""

    database: Path
    owner_login: str
    web_dir: Path | None = None
    # None until the coach's secrets exist; the Coach endpoints answer 503 then.
    coach: CoachSettings | None = None
    # The VAPID public key browsers subscribe with; None until push is set up.
    push_key: str | None = None


def settings_from_env(env: Mapping[str, str]) -> Settings:
    """Build settings from ``TRAINER_*`` variables (set by the systemd unit).

    The coach is configured when both ``TRAINER_HERMES_URL`` and the gateway's
    ``API_SERVER_KEY`` (from its root-only secrets file) are set. Push is
    configured when ``TRAINER_VAPID_PUBLIC_KEY`` is (``deploy/push-secrets.sh``).

    Raises:
        SettingsError: if the data directory or the owner's login is not set.
    """
    data_dir = env.get("TRAINER_DATA_DIR")
    owner = env.get("TRAINER_OWNER_LOGIN")
    if not data_dir or not owner:
        message = "TRAINER_DATA_DIR and TRAINER_OWNER_LOGIN must be set"
        raise SettingsError(message)
    web_dir = env.get("TRAINER_WEB_DIR")
    hermes_url, hermes_key = env.get("TRAINER_HERMES_URL"), env.get("API_SERVER_KEY")
    return Settings(
        database=Path(data_dir) / DATABASE_FILE,
        owner_login=owner,
        web_dir=Path(web_dir) if web_dir else None,
        coach=CoachSettings(hermes_url, hermes_key) if hermes_url and hermes_key else None,
        push_key=env.get("TRAINER_VAPID_PUBLIC_KEY") or None,
    )
