"""Rendering systemd units and the installer's variables."""

import shlex
from pathlib import Path, PurePosixPath

from trainer.deploy.config import DeployConfig
from trainer.deploy.render import UNITS, install_env, render_units, substitutions, write_bundle

CONFIG = DeployConfig(
    user="trainer",
    data_dir=PurePosixPath("/srv/trainer"),
    prefix=PurePosixPath("/opt/trainer"),
    bind_host="127.0.0.1",
    bind_port=8000,
    backup_keep=7,
)


def test_substitutions() -> None:
    assert substitutions(CONFIG) == {
        "user": "trainer",
        "data_dir": "/srv/trainer",
        "prefix": "/opt/trainer",
        "bind_host": "127.0.0.1",
        "bind_port": "8000",
        "backup_keep": "7",
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


def test_install_env_is_shell_quoted() -> None:
    config = DeployConfig(
        user="trainer",
        data_dir=PurePosixPath("/srv/trainer"),
        prefix=PurePosixPath("/opt/trainer"),
        bind_host="::1",
        bind_port=8000,
        backup_keep=7,
    )

    text = install_env(config)

    assert text == (
        "TRAINER_USER=trainer\n"
        "TRAINER_DATA_DIR=/srv/trainer\n"
        "TRAINER_PREFIX=/opt/trainer\n"
        f"TRAINER_UPSTREAM={shlex.quote('[::1]:8000')}\n"
    )


def test_write_bundle(tmp_path: Path) -> None:
    written = write_bundle(CONFIG, tmp_path / "out")

    assert [path.relative_to(tmp_path).as_posix() for path in written] == [
        "out/systemd/trainer-api.service",
        "out/systemd/trainer-backup.service",
        "out/systemd/trainer-backup.timer",
        "out/install.env",
    ]
    assert (tmp_path / "out/install.env").read_text() == install_env(CONFIG)
    rendered = render_units(CONFIG)["trainer-api.service"]
    assert (tmp_path / "out/systemd/trainer-api.service").read_text() == rendered


def test_write_bundle_overwrites_an_existing_bundle(tmp_path: Path) -> None:
    write_bundle(CONFIG, tmp_path)
    (tmp_path / "install.env").write_text("stale")

    write_bundle(CONFIG, tmp_path)

    assert (tmp_path / "install.env").read_text() == install_env(CONFIG)
