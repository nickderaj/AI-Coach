"""Deploy shell scripts and the committed example configuration."""

import re
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
        "hermes-secrets.sh",
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


@pytest.mark.parametrize(
    "script", ["hermes-secrets.sh", "import-v1.sh", "install.sh", "tailscale-serve.sh"]
)
def test_root_scripts_refuse_to_run_unprivileged(script: str) -> None:
    text = (DEPLOY / script).read_text(encoding="utf-8")

    assert '[ "$(id -u)" -ne 0 ]' in text


def test_example_env_is_valid_and_generic() -> None:
    config = load((DEPLOY / "local.env.example").read_text(encoding="utf-8"))

    assert config.user == "trainer"
    assert config.bind_host == "127.0.0.1"
    assert config.owner_login == "owner@example.com"


def test_hermes_is_built_from_a_pinned_commit() -> None:
    text = (DEPLOY / "build.sh").read_text(encoding="utf-8")

    assert re.search(r"^hermes_tag=v\d{4}\.\d{1,2}\.\d{1,2}$", text, re.MULTILINE)
    assert re.search(r"^hermes_commit=[0-9a-f]{40}$", text, re.MULTILINE)
    assert 'rev-parse HEAD)" != "$hermes_commit"' in text
    assert "uv export --quiet --locked" in text


def test_the_model_key_is_never_taken_as_an_argument() -> None:
    text = (DEPLOY / "hermes-secrets.sh").read_text(encoding="utf-8")

    assert "read -rsp" in text
    assert "umask 077" in text
    assert "chmod 0600" in text


def test_the_gateway_starts_only_with_its_secrets() -> None:
    text = (DEPLOY / "install.sh").read_text(encoding="utf-8")

    assert '[ -f "$TRAINER_SECRETS_DIR/model.env" ]' in text
    assert "--require-hashes" in text
    assert ".no-bundled-skills" in text


def test_the_old_coach_unit_is_removed_only_when_it_is_ours() -> None:
    text = (DEPLOY / "install.sh").read_text(encoding="utf-8")

    assert "grep -q '^Description=hermes-trainer coach' \"$legacy\"" in text


def test_the_v1_snapshot_is_read_only_and_made_as_its_owner() -> None:
    text = (DEPLOY / "import-v1.sh").read_text(encoding="utf-8")

    assert 'runuser -u "$owner" -- sqlite3 "file:$source_db?mode=ro"' in text
    assert 'owner=$(stat -c %U "$source_db")' in text
    assert '"${dry_run[@]}"' in text
