"""Deploy shell scripts and the committed example configuration."""

import shutil
import subprocess
from pathlib import Path

import pytest

from trainer.deploy.config import load

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SCRIPTS = sorted(DEPLOY.glob("*.sh"))


def test_there_are_deploy_scripts() -> None:
    assert [path.name for path in SCRIPTS] == [
        "build.sh",
        "import-v1.sh",
        "install.sh",
        "tailscale-serve.sh",
    ]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda path: path.name)
def test_script_parses_and_is_strict(script: Path) -> None:
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run([bash, "-n", str(script)], check=True)  # noqa: S603  # why: fixed argv over repository files

    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text


@pytest.mark.parametrize("script", ["import-v1.sh", "install.sh", "tailscale-serve.sh"])
def test_root_scripts_refuse_to_run_unprivileged(script: str) -> None:
    text = (DEPLOY / script).read_text(encoding="utf-8")

    assert '[ "$(id -u)" -ne 0 ]' in text


def test_example_env_is_valid_and_generic() -> None:
    config = load((DEPLOY / "local.env.example").read_text(encoding="utf-8"))

    assert config.user == "trainer"
    assert config.bind_host == "127.0.0.1"
    assert config.owner_login == "owner@example.com"
