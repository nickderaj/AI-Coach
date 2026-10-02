"""Host preflight: refuse unsafe accounts and directories before installing."""

import os
import pwd
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pytest

from trainer.deploy.config import DeployConfig
from trainer.deploy.preflight import (
    Account,
    Entry,
    SystemHost,
    check_account,
    check_ancestors,
    check_directory,
    check_prefix,
    preflight,
)

DIR = stat.S_IFDIR | 0o755
PRIVATE_DIR = stat.S_IFDIR | 0o750
ADMIN = 1000
SERVICE = 990
CONFIG = DeployConfig(
    user="trainer",
    data_dir=PurePosixPath("/mnt/media/trainer"),
    prefix=PurePosixPath("/opt/trainer"),
    bind_host="127.0.0.1",
    bind_port=8000,
    backup_keep=7,
    owner_login="owner@example.com",
    hermes_port=8642,
    model_url="https://api.example.com/v1",
    model="model-1",
    push_contact="mailto:owner@example.com",
)
GOOD_ACCOUNT = Account(
    uid=SERVICE, gid=SERVICE, home="/nonexistent", login_shell="/usr/sbin/nologin"
)


@dataclass
class FakeHost:
    accounts: dict[str, Account] = field(default_factory=dict)
    groups: dict[int, str] = field(default_factory=dict)
    entries: dict[str, Entry] = field(default_factory=dict)
    listings: dict[str, list[str]] = field(default_factory=dict)

    def account(self, name: str) -> Account | None:
        return self.accounts.get(name)

    def group_name(self, gid: int) -> str | None:
        return self.groups.get(gid)

    def group_exists(self, name: str) -> bool:
        return name in self.groups.values()

    def entry(self, path: PurePosixPath) -> Entry | None:
        return self.entries.get(str(path))

    def names(self, path: PurePosixPath) -> list[str]:
        return self.listings.get(str(path), [])


def standard_host() -> FakeHost:
    """A host like the owner's: root-owned roots, an admin-owned data drive."""
    return FakeHost(
        entries={
            "/": Entry(0, DIR),
            "/mnt": Entry(0, DIR),
            "/mnt/media": Entry(ADMIN, DIR),
            "/opt": Entry(0, DIR),
        }
    )


class TestAccount:
    def test_missing_account_is_fine(self) -> None:
        assert check_account("trainer", FakeHost()) == ([], None)

    def test_orphan_group_is_refused(self) -> None:
        host = FakeHost(groups={SERVICE: "trainer"})

        assert check_account("trainer", host) == (
            ["group 'trainer' exists without a matching user; refusing to reuse it"],
            None,
        )

    def test_dedicated_system_account_passes(self) -> None:
        host = FakeHost(accounts={"trainer": GOOD_ACCOUNT}, groups={SERVICE: "trainer"})

        assert check_account("trainer", host) == ([], SERVICE)

    @pytest.mark.parametrize("uid", [1, 999])
    def test_system_uid_bounds(self, uid: int) -> None:
        account = Account(uid=uid, gid=SERVICE, home="/nonexistent", login_shell="/bin/false")
        host = FakeHost(accounts={"trainer": account}, groups={SERVICE: "trainer"})

        assert check_account("trainer", host) == ([], uid)

    def test_every_mismatch_is_reported(self) -> None:
        account = Account(uid=0, gid=5, home="/root", login_shell="/bin/bash")
        host = FakeHost(accounts={"trainer": account}, groups={5: "wheel"})

        assert check_account("trainer", host) == (
            [
                "account 'trainer' has uid 0, not a system uid (1-999)",
                "account 'trainer' has primary group 'wheel', not 'trainer'",
                "account 'trainer' has home '/root', not '/nonexistent'",
                "account 'trainer' has login shell '/bin/bash'",
            ],
            0,
        )

    def test_regular_login_user_is_refused(self) -> None:
        account = Account(uid=1000, gid=1000, home="/nonexistent", login_shell="/sbin/nologin")
        host = FakeHost(accounts={"trainer": account}, groups={1000: "trainer"})

        problems, _ = check_account("trainer", host)

        assert problems == ["account 'trainer' has uid 1000, not a system uid (1-999)"]

    def test_unknown_primary_group_is_refused(self) -> None:
        host = FakeHost(accounts={"trainer": GOOD_ACCOUNT})

        problems, _ = check_account("trainer", host)

        assert problems == ["account 'trainer' has primary group None, not 'trainer'"]


class TestDirectory:
    path = PurePosixPath("/srv/x")

    def test_missing_directory_is_fine(self) -> None:
        assert check_directory(self.path, {0}, FakeHost()) == []

    def test_owned_private_directory_passes(self) -> None:
        host = FakeHost(entries={"/srv/x": Entry(0, DIR)})

        assert check_directory(self.path, {0}, host) == []

    @pytest.mark.parametrize("mode", [stat.S_IFLNK | 0o777, stat.S_IFREG | 0o644])
    def test_symlinks_and_files_are_refused(self, mode: int) -> None:
        host = FakeHost(entries={"/srv/x": Entry(0, mode)})

        assert check_directory(self.path, {0}, host) == [
            "/srv/x is not a real directory (symlinks are refused)"
        ]

    def test_wrong_owner_and_shared_write_are_both_reported(self) -> None:
        host = FakeHost(entries={"/srv/x": Entry(1234, stat.S_IFDIR | 0o775)})

        assert check_directory(self.path, {0, ADMIN}, host) == [
            "/srv/x is owned by uid 1234, expected one of [0, 1000]",
            "/srv/x is writable by its group or others",
        ]

    @pytest.mark.parametrize("mode", [0o757, 0o777, stat.S_ISVTX | 0o1777])
    def test_world_writable_is_refused(self, mode: int) -> None:
        host = FakeHost(entries={"/srv/x": Entry(0, stat.S_IFDIR | mode)})

        assert check_directory(self.path, {0}, host) == [
            "/srv/x is writable by its group or others"
        ]

    def test_existing_directory_without_service_account_is_refused(self) -> None:
        host = FakeHost(entries={"/srv/x": Entry(0, DIR)})

        assert check_directory(self.path, set(), host) == [
            "/srv/x already exists but the service account does not"
        ]


class TestAncestors:
    def test_checks_every_existing_ancestor_from_the_root(self) -> None:
        host = FakeHost(
            entries={
                "/": Entry(0, stat.S_IFDIR | 0o777),
                "/srv": Entry(7, DIR),
                "/srv/a": Entry(0, DIR),
            }
        )

        assert check_ancestors(PurePosixPath("/srv/a/b/c"), {0}, host) == [
            "/ is writable by its group or others",
            "/srv is owned by uid 7, expected one of [0]",
        ]

    def test_the_path_itself_is_not_an_ancestor(self) -> None:
        host = FakeHost(entries={"/": Entry(0, DIR), "/srv/x": Entry(7, DIR)})

        assert check_ancestors(PurePosixPath("/srv/x"), {0}, host) == []


class TestPrefix:
    path = PurePosixPath("/opt/trainer")

    def test_missing_prefix_is_fine(self) -> None:
        assert check_prefix(self.path, FakeHost()) == []

    def test_empty_prefix_is_fine(self) -> None:
        host = FakeHost(entries={"/opt/trainer": Entry(0, DIR)})

        assert check_prefix(self.path, host) == []

    def test_marked_prefix_is_fine(self) -> None:
        host = FakeHost(
            entries={"/opt/trainer": Entry(0, DIR)},
            listings={"/opt/trainer": [".hermes-trainer", "venv"]},
        )

        assert check_prefix(self.path, host) == []

    def test_foreign_contents_are_refused(self) -> None:
        host = FakeHost(
            entries={"/opt/trainer": Entry(0, DIR)}, listings={"/opt/trainer": ["bin", "lib"]}
        )

        assert check_prefix(self.path, host) == [
            "/opt/trainer is not empty and not a hermes-trainer prefix; refusing to use it"
        ]

    def test_non_root_owner_is_refused_before_listing(self) -> None:
        host = FakeHost(
            entries={"/opt/trainer": Entry(ADMIN, DIR)}, listings={"/opt/trainer": ["bin"]}
        )

        assert check_prefix(self.path, host) == [
            "/opt/trainer is owned by uid 1000, expected one of [0]"
        ]


class TestPreflight:
    def test_fresh_host_passes(self) -> None:
        assert preflight(CONFIG, standard_host(), ADMIN) == []

    def test_reinstall_passes(self) -> None:
        host = standard_host()
        host.accounts["trainer"] = GOOD_ACCOUNT
        host.groups[SERVICE] = "trainer"
        host.entries["/mnt/media/trainer"] = Entry(SERVICE, PRIVATE_DIR)
        host.entries["/opt/trainer"] = Entry(0, DIR)
        host.listings["/opt/trainer"] = [".hermes-trainer", "venv"]

        assert preflight(CONFIG, host, ADMIN) == []

    def test_data_ancestor_owned_by_another_user_is_refused(self) -> None:
        assert preflight(CONFIG, standard_host(), 1001) == [
            "/mnt/media is owned by uid 1000, expected one of [0, 1001]"
        ]

    def test_prefix_ancestors_must_be_root_owned(self) -> None:
        host = standard_host()
        host.entries["/opt"] = Entry(ADMIN, DIR)

        assert preflight(CONFIG, host, ADMIN) == ["/opt is owned by uid 1000, expected one of [0]"]

    def test_existing_data_dir_owned_by_someone_else_is_refused(self) -> None:
        host = standard_host()
        host.accounts["trainer"] = GOOD_ACCOUNT
        host.groups[SERVICE] = "trainer"
        host.entries["/mnt/media/trainer"] = Entry(ADMIN, PRIVATE_DIR)

        assert preflight(CONFIG, host, ADMIN) == [
            "/mnt/media/trainer is owned by uid 1000, expected one of [990]"
        ]

    def test_existing_data_dir_before_the_account_exists_is_refused(self) -> None:
        host = standard_host()
        host.entries["/mnt/media/trainer"] = Entry(0, DIR)

        assert preflight(CONFIG, host, ADMIN) == [
            "/mnt/media/trainer already exists but the service account does not"
        ]

    def test_problems_from_every_check_are_combined(self) -> None:
        host = standard_host()
        host.groups[SERVICE] = "trainer"
        host.entries["/opt/trainer"] = Entry(0, DIR)
        host.listings["/opt/trainer"] = ["etc"]

        assert preflight(CONFIG, host, ADMIN) == [
            "group 'trainer' exists without a matching user; refusing to reuse it",
            "/opt/trainer is not empty and not a hermes-trainer prefix; refusing to use it",
        ]


class TestSystemHost:
    def test_reads_the_current_user_and_group(self) -> None:
        me = pwd.getpwuid(os.getuid())
        host = SystemHost()

        account = host.account(me.pw_name)

        assert account == Account(me.pw_uid, me.pw_gid, me.pw_dir, me.pw_shell)
        group = host.group_name(me.pw_gid)
        assert group is not None
        assert host.group_exists(group)

    def test_unknown_names_are_none(self) -> None:
        host = SystemHost()

        assert host.account("no-such-user-for-tests") is None
        assert host.group_name(2**31 - 7) is None
        assert host.group_exists("no-such-group-for-tests") is False

    def test_entry_uses_lstat_and_names_lists_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b").mkdir()
        (tmp_path / "a").write_text("x")
        (tmp_path / "link").symlink_to(tmp_path / "b")
        host = SystemHost()

        entry = host.entry(PurePosixPath(tmp_path / "link"))

        assert entry is not None
        assert stat.S_ISLNK(entry.mode)
        assert entry.uid == os.getuid()
        assert host.entry(PurePosixPath(tmp_path / "missing")) is None
        assert host.names(PurePosixPath(tmp_path)) == ["a", "b", "link"]
