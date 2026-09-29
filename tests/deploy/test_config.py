"""Deployment configuration parsing and validation."""

from pathlib import PurePosixPath

import pytest

from trainer.deploy.config import ConfigError, DeployConfig, load, parse_env

VALID = {
    "TRAINER_USER": "trainer",
    "TRAINER_DATA_DIR": "/srv/hermes-trainer",
    "TRAINER_PREFIX": "/opt/hermes-trainer",
    "TRAINER_BIND_HOST": "127.0.0.1",
    "TRAINER_BIND_PORT": "8000",
    "TRAINER_BACKUP_KEEP": "14",
}


def document(**overrides: str | None) -> str:
    values = {**VALID, **overrides}
    return "".join(f"{key}={value}\n" for key, value in values.items() if value is not None)


def error_for(**overrides: str | None) -> str:
    with pytest.raises(ConfigError) as caught:
        load(document(**overrides))
    return str(caught.value)


class TestParseEnv:
    def test_reads_pairs_and_skips_comments_and_blanks(self) -> None:
        text = "# comment\n\n  A = 1 \nB=two=parts\nC=\n"

        assert parse_env(text) == {"A": "1", "B": "two=parts", "C": ""}

    def test_line_without_separator_is_an_error(self) -> None:
        with pytest.raises(ConfigError, match=r"^line 2: expected KEY=VALUE$"):
            parse_env("A=1\nnonsense\n")

    def test_duplicate_key_is_an_error(self) -> None:
        with pytest.raises(ConfigError, match=r"^line 3: A is set twice$"):
            parse_env("A=1\n# x\nA=2\n")


class TestLoad:
    def test_valid_document(self) -> None:
        assert load(document()) == DeployConfig(
            user="trainer",
            data_dir=PurePosixPath("/srv/hermes-trainer"),
            prefix=PurePosixPath("/opt/hermes-trainer"),
            bind_host="127.0.0.1",
            bind_port=8000,
            backup_keep=14,
        )

    def test_missing_keys_are_listed_in_order(self) -> None:
        assert error_for(TRAINER_USER=None, TRAINER_BIND_PORT=None) == (
            "missing TRAINER_USER, TRAINER_BIND_PORT"
        )

    def test_unknown_keys_are_listed_sorted(self) -> None:
        text = document() + "ZED=1\nALPHA=2\n"

        with pytest.raises(ConfigError, match=r"^unknown ALPHA, ZED$"):
            load(text)

    @pytest.mark.parametrize("user", ["trainer", "_svc", "a", "gym-2", "a" * 32])
    def test_valid_users(self, user: str) -> None:
        assert load(document(TRAINER_USER=user)).user == user

    @pytest.mark.parametrize("user", ["", "Trainer", "1abc", "a b", "a" * 33, "root;rm"])
    def test_invalid_users(self, user: str) -> None:
        assert error_for(TRAINER_USER=user) == (
            f"TRAINER_USER {user!r} is not a valid system user name"
        )

    @pytest.mark.parametrize("path", ["/srv/x", "/a/b.c/d_e-f", "/a"])
    def test_valid_paths(self, path: str) -> None:
        assert load(document(TRAINER_DATA_DIR=path)).data_dir == PurePosixPath(path)

    @pytest.mark.parametrize(
        "path", ["", "/", "relative/x", "/a/../b", "/a b", "/a/$(x)", "/a//b", "/a/"]
    )
    def test_invalid_paths(self, path: str) -> None:
        for key in ("TRAINER_DATA_DIR", "TRAINER_PREFIX"):
            assert error_for(**{key: path}) == (
                f"{key} {path!r} must be an absolute path of plain segments"
            )

    @pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.1", "::1"])
    def test_loopback_hosts_are_accepted(self, host: str) -> None:
        assert load(document(TRAINER_BIND_HOST=host)).bind_host == host

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.2", "::", "localhost", ""])  # noqa: S104  # why: asserting that wildcard binds are rejected
    def test_non_loopback_hosts_are_rejected(self, host: str) -> None:
        assert error_for(TRAINER_BIND_HOST=host) == (
            f"TRAINER_BIND_HOST {host!r} must be a loopback address; "
            "tailscale serve is the only way in"
        )

    @pytest.mark.parametrize(("port", "expected"), [("1024", 1024), ("65535", 65535)])
    def test_port_bounds_are_inclusive(self, port: str, expected: int) -> None:
        assert load(document(TRAINER_BIND_PORT=port)).bind_port == expected

    @pytest.mark.parametrize("port", ["1023", "65536", "-1", "80a", ""])
    def test_invalid_ports(self, port: str) -> None:
        assert error_for(TRAINER_BIND_PORT=port) == (
            f"TRAINER_BIND_PORT {port!r} must be an integer from 1024 to 65535"
        )

    @pytest.mark.parametrize(("keep", "expected"), [("1", 1), ("365", 365)])
    def test_backup_keep_bounds_are_inclusive(self, keep: str, expected: int) -> None:
        assert load(document(TRAINER_BACKUP_KEEP=keep)).backup_keep == expected

    @pytest.mark.parametrize("keep", ["0", "366"])
    def test_invalid_backup_keep(self, keep: str) -> None:
        assert error_for(TRAINER_BACKUP_KEEP=keep) == (
            f"TRAINER_BACKUP_KEEP {keep!r} must be an integer from 1 to 365"
        )


@pytest.mark.parametrize(
    ("host", "upstream"), [("127.0.0.1", "127.0.0.1:8000"), ("::1", "[::1]:8000")]
)
def test_upstream_brackets_ipv6(host: str, upstream: str) -> None:
    assert load(document(TRAINER_BIND_HOST=host)).upstream == upstream
