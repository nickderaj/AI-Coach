"""The coach's Hermes profile: what it may do, and that it holds nothing private."""

import re
from pathlib import Path

import pytest

from trainer.deploy.config import load
from trainer.deploy.render import install_env, render_units

HERMES = Path(__file__).resolve().parents[2] / "hermes"
EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "local.env.example"
EXAMPLE_TEXT = EXAMPLE.read_text(encoding="utf-8")
CONFIG = (HERMES / "config.yaml").read_text(encoding="utf-8")
ALLOWED = "[memory, session_search, skills, todo, clarify, mcp-trainer]"


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


def test_the_conversation_is_compacted_early() -> None:
    lines = CONFIG.splitlines()

    # Each message resends the conversation: its length is what a message costs.
    assert "compression:" in lines
    assert "  threshold_tokens: 32000" in lines


def test_the_tool_server_is_the_trainers_own_module() -> None:
    lines = CONFIG.splitlines()

    assert "    command: ${TRAINER_PREFIX}/venv/bin/python" in lines
    assert "    args: [-m, trainer.mcp]" in lines
    assert "      TRAINER_DATA_DIR: ${TRAINER_DATA_DIR}" in lines
    assert "      enabled: false" in lines  # no sampling: the server never calls the model


def test_the_api_server_listens_on_loopback_only() -> None:
    lines = CONFIG.splitlines()

    assert "    host: ${TRAINER_HERMES_HOST}" in lines  # TRAINER_BIND_HOST: loopback
    assert "    port: ${TRAINER_HERMES_PORT}" in lines


def test_every_placeholder_is_set_by_the_gateway_unit() -> None:
    unit = render_units(load(EXAMPLE.read_text(encoding="utf-8")))["trainer-coach.service"]
    environment = set(re.findall(r"^Environment=([A-Z_]+)=", unit, re.MULTILINE))
    # The gateway's key comes from its root-only secrets file.
    assert "EnvironmentFile=/etc/hermes-trainer/gateway.env" in unit.splitlines()
    environment.add("API_SERVER_KEY")

    assert set(re.findall(r"\$\{([A-Z_]+)\}", CONFIG)) == {
        "TRAINER_MODEL",
        "TRAINER_MODEL_URL",
        "TRAINER_HERMES_HOST",
        "TRAINER_HERMES_PORT",
        "TRAINER_PREFIX",
        "TRAINER_DATA_DIR",
        "TRAINER_API_URL",
        "API_SERVER_KEY",
    }
    assert set(re.findall(r"\$\{([A-Z_]+)\}", CONFIG)) <= environment


def test_the_tool_server_proposes_through_the_api_with_the_gateways_key() -> None:
    lines = CONFIG.splitlines()

    assert "      TRAINER_API_URL: ${TRAINER_API_URL}" in lines
    assert "      TRAINER_COACH_KEY: ${API_SERVER_KEY}" in lines


@pytest.mark.parametrize(
    ("bind_host", "url"),
    [("127.0.0.1", "http://127.0.0.1:8000"), ("::1", "http://[::1]:8000")],
)
def test_the_coach_finds_the_api_where_it_listens(bind_host: str, url: str) -> None:
    config = load(
        EXAMPLE_TEXT.replace("TRAINER_BIND_HOST=127.0.0.1", f"TRAINER_BIND_HOST={bind_host}")
    )

    unit = render_units(config)["trainer-coach.service"].splitlines()

    assert f"Environment=TRAINER_API_URL={url}" in unit


def test_keys_are_named_never_written() -> None:
    assert "    key_env: TRAINER_MODEL_API_KEY" in CONFIG.splitlines()
    assert not re.search(r"^\s*(?:api_)?key:", CONFIG, re.MULTILINE)


@pytest.mark.parametrize(
    ("bind_host", "upstream"),
    [
        ("127.0.0.1", "127.0.0.1:8642"),
        ("127.0.0.2", "127.0.0.2:8642"),
        ("::1", "'[::1]:8642'"),
    ],
)
def test_the_gateway_listens_where_the_api_and_installer_look(
    bind_host: str, upstream: str
) -> None:
    config = load(
        EXAMPLE_TEXT.replace("TRAINER_BIND_HOST=127.0.0.1", f"TRAINER_BIND_HOST={bind_host}")
    )
    unit = render_units(config)["trainer-coach.service"].splitlines()

    # The gateway binds ${TRAINER_HERMES_HOST} (above), which the unit sets to the
    # API's address; the installer's health check and the API use the same one.
    assert f"Environment=TRAINER_HERMES_HOST={bind_host}" in unit
    assert f"TRAINER_HERMES_UPSTREAM={upstream}" in install_env(config).splitlines()
    assert config.hermes_upstream == upstream.strip("'")
