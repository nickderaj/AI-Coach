"""The coach's Hermes profile: what it may do, and that it holds nothing private."""

import re
from pathlib import Path

from trainer.deploy.config import load
from trainer.deploy.render import render_units

HERMES = Path(__file__).resolve().parents[2] / "hermes"
EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "local.env.example"
CONFIG = (HERMES / "config.yaml").read_text(encoding="utf-8")
ALLOWED = "[memory, session_search, skills, todo, clarify]"


def test_the_profile_is_the_config_and_the_soul() -> None:
    assert sorted(path.name for path in HERMES.iterdir()) == ["SOUL.md", "config.yaml"]


def test_learning_is_on_and_nothing_else_is_allowed() -> None:
    lines = CONFIG.splitlines()

    assert f"toolsets: {ALLOWED}" in lines
    assert f"  api_server: {ALLOWED}" in lines
    for toolset in ("terminal", "file", "web", "browser", "code_execution", "delegation"):
        assert f"    - {toolset}" in lines
    assert '    enabled: "off"' in lines  # no tool-search bridge
    assert "  allow_lazy_installs: false" in lines  # no pip installs at runtime


def test_the_api_server_listens_on_loopback_only() -> None:
    lines = CONFIG.splitlines()

    assert "    host: 127.0.0.1" in lines
    assert "    port: ${TRAINER_HERMES_PORT}" in lines


def test_every_placeholder_is_set_by_the_gateway_unit() -> None:
    unit = render_units(load(EXAMPLE.read_text(encoding="utf-8")))["hermes-gateway.service"]
    environment = set(re.findall(r"^Environment=([A-Z_]+)=", unit, re.MULTILINE))

    assert set(re.findall(r"\$\{([A-Z_]+)\}", CONFIG)) == {
        "TRAINER_MODEL",
        "TRAINER_MODEL_URL",
        "TRAINER_HERMES_PORT",
    }
    assert set(re.findall(r"\$\{([A-Z_]+)\}", CONFIG)) <= environment


def test_keys_are_named_never_written() -> None:
    assert "    key_env: TRAINER_MODEL_API_KEY" in CONFIG.splitlines()
    assert not re.search(r"^\s*(?:api_)?key:", CONFIG, re.MULTILINE)
