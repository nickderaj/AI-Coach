"""Rendering systemd units and the installer's variables."""

import shlex
from pathlib import Path, PurePosixPath

from trainer.deploy.config import DeployConfig, to_env
from trainer.deploy.render import UNITS, install_env, render_units, substitutions, write_bundle

CONFIG = DeployConfig(
    user="trainer",
    data_dir=PurePosixPath("/srv/trainer"),
    prefix=PurePosixPath("/opt/trainer"),
    bind_host="127.0.0.1",
    bind_port=8000,
    backup_keep=7,
    owner_login="owner@example.com",
    hermes_port=8642,
    model_url="https://api.example.com/v1",
    model="model-1",
)


def test_substitutions() -> None:
    assert substitutions(CONFIG) == {
        "user": "trainer",
        "data_dir": "/srv/trainer",
        "prefix": "/opt/trainer",
        "bind_host": "127.0.0.1",
        "bind_port": "8000",
        "backup_keep": "7",
        "owner_login": "owner@example.com",
        "hermes_port": "8642",
        "hermes_upstream": "127.0.0.1:8642",
        "model_url": "https://api.example.com/v1",
        "model": "model-1",
        "hermes_home": "/srv/trainer/hermes",
        "memory_repo": "/srv/trainer/hermes-memory.git",
        "secrets_dir": "/etc/hermes-trainer",
    }


def test_every_unit_is_rendered_without_leftover_placeholders() -> None:
    units = render_units(CONFIG)

    assert list(units) == list(UNITS)
    for content in units.values():
        assert "${" not in content


def test_api_unit_runs_the_app_as_the_service_user_on_loopback() -> None:
    lines = render_units(CONFIG)["trainer-api.service"].splitlines()

    for expected in (
        "User=trainer",
        "Group=trainer",
        "Environment=TRAINER_DATA_DIR=/srv/trainer",
        "Environment=TRAINER_WEB_DIR=/opt/trainer/web",
        "Environment=TRAINER_OWNER_LOGIN=owner@example.com",
        "Environment=TRAINER_HERMES_URL=http://127.0.0.1:8642",
        "EnvironmentFile=-/etc/hermes-trainer/gateway.env",
        "ExecStart=/opt/trainer/venv/bin/python -m trainer.api --host 127.0.0.1 --port 8000",
        "ReadWritePaths=/srv/trainer",
        "ProtectSystem=strict",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=",
        "IPAddressDeny=any",
        "IPAddressAllow=localhost",
        "WantedBy=multi-user.target",
    ):
        assert expected in lines


def test_backup_unit_has_no_network_and_rotates() -> None:
    lines = render_units(CONFIG)["trainer-backup.service"].splitlines()

    for expected in (
        "Type=oneshot",
        "User=trainer",
        (
            "ExecStart=/opt/trainer/venv/bin/python -m trainer.deploy backup "
            "--data-dir /srv/trainer --keep 7"
        ),
        "PrivateNetwork=yes",
        "RestrictAddressFamilies=AF_UNIX",
    ):
        assert expected in lines


def test_timer_is_nightly_and_persistent() -> None:
    lines = render_units(CONFIG)["trainer-backup.timer"].splitlines()

    assert "OnCalendar=*-*-* 03:30:00" in lines
    assert "Persistent=true" in lines


def test_gateway_unit_runs_hermes_with_root_only_secrets() -> None:
    lines = render_units(CONFIG)["trainer-coach.service"].splitlines()

    for expected in (
        "Wants=network-online.target trainer-api.service",
        "After=network-online.target trainer-api.service",
        "User=trainer",
        "Group=trainer",
        "Environment=HERMES_HOME=/srv/trainer/hermes",
        "Environment=HOME=/srv/trainer/hermes",
        "Environment=TRAINER_DATA_DIR=/srv/trainer",
        "Environment=TRAINER_PREFIX=/opt/trainer",
        "Environment=TRAINER_MODEL=model-1",
        "Environment=TRAINER_MODEL_URL=https://api.example.com/v1",
        "Environment=TRAINER_HERMES_HOST=127.0.0.1",
        "Environment=TRAINER_HERMES_PORT=8642",
        "Environment=HERMES_DISABLE_LAZY_INSTALLS=1",
        "EnvironmentFile=/etc/hermes-trainer/model.env",
        "EnvironmentFile=/etc/hermes-trainer/gateway.env",
        "ExecStart=/opt/trainer/hermes/bin/python -m hermes_cli.main gateway run",
        "ReadWritePaths=/srv/trainer/hermes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "NoNewPrivileges=yes",
        "CapabilityBoundingSet=",
        "MemoryDenyWriteExecute=yes",
        "SystemCallFilter=@system-service",
        "SystemCallFilter=~@resources @setuid capset",
        "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
        "WantedBy=multi-user.target",
    ):
        assert expected in lines
    # The whole data directory (the training database) is not the gateway's to write.
    assert "ReadWritePaths=/srv/trainer" not in lines


def test_no_unit_takes_the_name_hermes_installs_its_own_gateway_under() -> None:
    # `hermes gateway install` creates hermes-gateway.service, and other Hermes
    # installs on the host (with drop-ins of their own) may already use it.
    assert "hermes-gateway.service" not in UNITS


def test_every_unit_runs_python_from_its_venv_not_a_console_script() -> None:
    # Venvs are built in a staging directory and moved, so console scripts' #!
    # lines point at a path that no longer exists.
    for content in render_units(CONFIG).values():
        for line in content.splitlines():
            if line.startswith("ExecStart="):
                assert line.split()[0].endswith("/bin/python"), line


def test_memory_unit_commits_offline() -> None:
    lines = render_units(CONFIG)["trainer-memory.service"].splitlines()

    for expected in (
        "Type=oneshot",
        "User=trainer",
        (
            "ExecStart=/opt/trainer/venv/bin/python -m trainer.deploy memory-commit "
            "--hermes-home /srv/trainer/hermes --repo /srv/trainer/hermes-memory.git"
        ),
        "ReadWritePaths=/srv/trainer/hermes-memory.git",
        "ReadOnlyPaths=/srv/trainer/hermes",
        "PrivateNetwork=yes",
        "RestrictAddressFamilies=AF_UNIX",
    ):
        assert expected in lines


def test_memory_timer_runs_nightly_before_the_backup() -> None:
    lines = render_units(CONFIG)["trainer-memory.timer"].splitlines()

    assert "OnCalendar=*-*-* 03:15:00" in lines
    assert "Persistent=true" in lines


def test_install_env_is_shell_quoted() -> None:
    config = DeployConfig(
        user="trainer",
        data_dir=PurePosixPath("/srv/trainer"),
        prefix=PurePosixPath("/opt/trainer"),
        bind_host="::1",
        bind_port=8000,
        backup_keep=7,
        owner_login="owner@example.com",
        hermes_port=8642,
        model_url="https://api.example.com/v1",
        model="model-1",
    )

    text = install_env(config)

    assert text == (
        "TRAINER_USER=trainer\n"
        "TRAINER_DATA_DIR=/srv/trainer\n"
        "TRAINER_PREFIX=/opt/trainer\n"
        f"TRAINER_UPSTREAM={shlex.quote('[::1]:8000')}\n"
        f"TRAINER_HERMES_UPSTREAM={shlex.quote('[::1]:8642')}\n"
        "TRAINER_HERMES_HOME=/srv/trainer/hermes\n"
        "TRAINER_MEMORY_REPO=/srv/trainer/hermes-memory.git\n"
        "TRAINER_SECRETS_DIR=/etc/hermes-trainer\n"
    )


def test_write_bundle(tmp_path: Path) -> None:
    written = write_bundle(CONFIG, tmp_path / "out")

    assert [path.relative_to(tmp_path).as_posix() for path in written] == [
        "out/systemd/trainer-api.service",
        "out/systemd/trainer-backup.service",
        "out/systemd/trainer-backup.timer",
        "out/systemd/trainer-coach.service",
        "out/systemd/trainer-memory.service",
        "out/systemd/trainer-memory.timer",
        "out/install.env",
        "out/config.env",
    ]
    assert (tmp_path / "out/install.env").read_text() == install_env(CONFIG)
    assert (tmp_path / "out/config.env").read_text() == to_env(CONFIG)
    rendered = render_units(CONFIG)["trainer-api.service"]
    assert (tmp_path / "out/systemd/trainer-api.service").read_text() == rendered


def test_write_bundle_overwrites_an_existing_bundle(tmp_path: Path) -> None:
    write_bundle(CONFIG, tmp_path)
    (tmp_path / "install.env").write_text("stale")

    write_bundle(CONFIG, tmp_path)

    assert (tmp_path / "install.env").read_text() == install_env(CONFIG)
