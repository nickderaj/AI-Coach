"""Deployment configuration parsing and validation."""

from pathlib import PurePosixPath

import pytest

from trainer.deploy.config import (
    DATA_ROOTS,
    PREFIX_ROOTS,
    ConfigError,
    DeployConfig,
    load,
    parse_env,
    to_env,
)

VALID = {
    "TRAINER_USER": "trainer",
    "TRAINER_DATA_DIR": "/srv/hermes-trainer",
    "TRAINER_PREFIX": "/opt/hermes-trainer",
    "TRAINER_BIND_HOST": "127.0.0.1",
    "TRAINER_BIND_PORT": "8000",
    "TRAINER_BACKUP_KEEP": "14",
    "TRAINER_OWNER_LOGIN": "owner@example.com",
    "TRAINER_HERMES_PORT": "8642",
    "TRAINER_MODEL_URL": "https://api.example.com/v1",
    "TRAINER_MODEL": "model-1",
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
            owner_login="owner@example.com",
            hermes_port=8642,
            model_url="https://api.example.com/v1",
            model="model-1",
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

    @pytest.mark.parametrize("user", ["root", "nobody"])
    def test_reserved_users(self, user: str) -> None:
        assert error_for(TRAINER_USER=user) == (
            f"TRAINER_USER {user!r} is reserved; use a dedicated service account"
        )

    @pytest.mark.parametrize("path", ["/srv/x", "/var/lib/a/b.c", "/mnt/media/gym", "/media/d_e-f"])
    def test_valid_data_dirs(self, path: str) -> None:
        assert load(document(TRAINER_DATA_DIR=path)).data_dir == PurePosixPath(path)

    @pytest.mark.parametrize("path", ["/opt/x", "/usr/local/lib/trainer"])
    def test_valid_prefixes(self, path: str) -> None:
        assert load(document(TRAINER_PREFIX=path)).prefix == PurePosixPath(path)

    @pytest.mark.parametrize(
        "path",
        ["", "/", "relative/x", "/srv/../etc", "/srv/./x", "/a b", "/a/$(x)", "/a//b", "/a/"],
    )
    def test_malformed_paths(self, path: str) -> None:
        for key in ("TRAINER_DATA_DIR", "TRAINER_PREFIX"):
            assert error_for(**{key: path}) == (
                f"{key} {path!r} must be an absolute path of plain segments"
            )

    @pytest.mark.parametrize(
        "path", ["/etc", "/usr", "/srv", "/var/lib", "/srvx/y", "/home/someone/data", "/opt/x"]
    )
    def test_data_dir_must_be_dedicated_under_a_data_root(self, path: str) -> None:
        assert error_for(TRAINER_DATA_DIR=path) == (
            f"TRAINER_DATA_DIR {path!r} must be a dedicated directory inside "
            "/srv or /var/lib or /mnt or /media"
        )

    @pytest.mark.parametrize(
        "path", ["/usr", "/opt", "/usr/local", "/etc/x", "/srv/x", "/srv/hermes-trainer/code"]
    )
    def test_prefix_must_be_dedicated_under_a_prefix_root(self, path: str) -> None:
        assert error_for(TRAINER_PREFIX=path) == (
            f"TRAINER_PREFIX {path!r} must be a dedicated directory inside /opt or /usr/local"
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

    @pytest.mark.parametrize("login", ["owner@example.com", "someone@github", "a", "x" * 254])
    def test_valid_logins(self, login: str) -> None:
        assert load(document(TRAINER_OWNER_LOGIN=login)).owner_login == login

    @pytest.mark.parametrize("login", ["", "a b@example.com", "50%@example.com", "x" * 255, "a;b"])
    def test_invalid_logins(self, login: str) -> None:
        assert error_for(TRAINER_OWNER_LOGIN=login) == (
            f"TRAINER_OWNER_LOGIN {login!r} is not a valid Tailscale login"
        )

    @pytest.mark.parametrize(("keep", "expected"), [("1", 1), ("365", 365)])
    def test_backup_keep_bounds_are_inclusive(self, keep: str, expected: int) -> None:
        assert load(document(TRAINER_BACKUP_KEEP=keep)).backup_keep == expected

    @pytest.mark.parametrize("keep", ["0", "366"])
    def test_invalid_backup_keep(self, keep: str) -> None:
        assert error_for(TRAINER_BACKUP_KEEP=keep) == (
            f"TRAINER_BACKUP_KEEP {keep!r} must be an integer from 1 to 365"
        )

    @pytest.mark.parametrize(("port", "expected"), [("1024", 1024), ("65535", 65535)])
    def test_hermes_port_bounds_are_inclusive(self, port: str, expected: int) -> None:
        assert load(document(TRAINER_HERMES_PORT=port)).hermes_port == expected

    @pytest.mark.parametrize("port", ["1023", "65536", "x"])
    def test_invalid_hermes_ports(self, port: str) -> None:
        assert error_for(TRAINER_HERMES_PORT=port) == (
            f"TRAINER_HERMES_PORT {port!r} must be an integer from 1024 to 65535"
        )

    def test_hermes_port_must_differ_from_the_api_port(self) -> None:
        assert error_for(TRAINER_HERMES_PORT="8000") == (
            "TRAINER_HERMES_PORT '8000' must differ from TRAINER_BIND_PORT"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.example.com/v1",
            "https://api.example.com",
            "https://api.example.com/",
            "https://llm.internal:8443/openai/v1/",
            "https://a/b_c/d~e/f.g",
        ],
    )
    def test_valid_model_urls(self, url: str) -> None:
        assert load(document(TRAINER_MODEL_URL=url)).model_url == url

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "http://api.example.com/v1",  # never in clear text
            "https://",
            "https://api.example.com/v1?key=x",
            "https://api.example.com/%2e",
            "https://${HOST}/v1",
            "https://api.example.com//v1",
            "https://api.example.com:123456/v1",
            "https://user@example.com/v1",
        ],
    )
    def test_invalid_model_urls(self, url: str) -> None:
        assert error_for(TRAINER_MODEL_URL=url).startswith(
            f"TRAINER_MODEL_URL {url!r} is not allowed (expected ^https://"
        )

    @pytest.mark.parametrize(
        "model", ["gpt-6-astra", "a", "openai/gpt-5.4", "org/model:free", "M_1", "x" * 100]
    )
    def test_valid_models(self, model: str) -> None:
        assert load(document(TRAINER_MODEL=model)).model == model

    @pytest.mark.parametrize("model", ["", "-x", "a b", "x" * 101, "$MODEL", "a%b", "/x"])
    def test_invalid_models(self, model: str) -> None:
        expected = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$"
        assert error_for(TRAINER_MODEL=model) == (
            f"TRAINER_MODEL {model!r} is not allowed (expected {expected})"
        )


@pytest.mark.parametrize(
    ("host", "upstream", "hermes"),
    [("127.0.0.1", "127.0.0.1:8000", "127.0.0.1:8642"), ("::1", "[::1]:8000", "[::1]:8642")],
)
def test_upstreams_bracket_ipv6(host: str, upstream: str, hermes: str) -> None:
    config = load(document(TRAINER_BIND_HOST=host))

    assert (config.upstream, config.hermes_upstream) == (upstream, hermes)


def test_data_and_prefix_roots_cannot_overlap() -> None:
    """Disjoint roots mean the writable data dir can never contain (or be) the code."""
    for data_root in map(PurePosixPath, DATA_ROOTS):
        for prefix_root in map(PurePosixPath, PREFIX_ROOTS):
            assert not data_root.is_relative_to(prefix_root)
            assert not prefix_root.is_relative_to(data_root)


def test_to_env_round_trips() -> None:
    config = load(document())

    assert to_env(config) == document()
    assert load(to_env(config)) == config
