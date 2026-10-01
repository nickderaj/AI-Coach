"""The nightly commit of the coach's memory to its private repository."""

import shutil
import subprocess
from pathlib import Path

import pytest

from trainer.deploy.memory import MemoryRepoError, commit_memory


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A Hermes home with memory, a skill, and things that must never be recorded."""
    home = tmp_path / "hermes"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "USER.md").write_text("Prefers 8-12 reps.\n")
    (home / "memories" / "USER.md.lock").write_text("")
    (home / "skills" / "deload").mkdir(parents=True)
    (home / "skills" / "deload" / "SKILL.md").write_text("# Deload\n")
    (home / "sessions").mkdir()
    (home / "sessions" / "s1.json").write_text("{}")
    (home / "state.db").write_bytes(b"sqlite")
    (home / "config.yaml").write_text("model: {}\n")
    return home


def git(repo: Path, *args: str) -> str:
    executable = shutil.which("git")
    assert executable is not None
    return subprocess.run(  # noqa: S603  # why: fixed git argv over a temporary repository
        [executable, f"--git-dir={repo}", *args], check=True, capture_output=True, text=True
    ).stdout


def test_the_first_run_creates_the_repository_and_records_only_memory_and_skills(
    home: Path, tmp_path: Path
) -> None:
    repo = tmp_path / "memory.git"

    commit = commit_memory(home, repo)

    assert commit == git(repo, "rev-parse", "HEAD").strip()
    assert git(repo, "ls-tree", "-r", "--name-only", "HEAD").split() == [
        "memories/USER.md",
        "skills/deload/SKILL.md",
    ]
    assert git(repo, "log", "--format=%an <%ae>|%cn <%ce>|%s").strip() == (
        "hermes-trainer <hermes@localhost>|hermes-trainer <hermes@localhost>|"
        "Learned since the last commit"
    )
    assert git(repo, "rev-parse", "--is-bare-repository").strip() == "true"
    assert git(repo, "symbolic-ref", "HEAD").strip() == "refs/heads/main"
    assert not (home / ".git").exists()


def test_nothing_changed_means_no_commit(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "memory.git"
    first = commit_memory(home, repo)
    (home / "sessions" / "s2.json").write_text("{}")  # not tracked
    (home / "state.db").write_bytes(b"changed")

    assert commit_memory(home, repo) is None
    assert git(repo, "rev-parse", "HEAD").strip() == first


def test_edits_additions_and_deletions_are_recorded(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "memory.git"
    commit_memory(home, repo)
    (home / "memories" / "USER.md").write_text("Prefers 6-10 reps.\n")
    (home / "memories" / "MEMORY.md").write_text("Left shoulder sore.\n")
    shutil.rmtree(home / "skills")

    commit = commit_memory(home, repo)

    assert commit is not None
    assert git(repo, "show", "--name-status", "--format=%s", "HEAD").split("\n") == [
        "Learned since the last commit",
        "",
        "A\tmemories/MEMORY.md",
        "M\tmemories/USER.md",
        "D\tskills/deload/SKILL.md",
        "",
    ]
    assert git(repo, "rev-list", "--count", "HEAD").strip() == "2"


def test_a_home_with_nothing_learned_yet_commits_nothing(tmp_path: Path) -> None:
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "state.db").write_bytes(b"sqlite")

    assert commit_memory(home, tmp_path / "memory.git") is None


def test_a_repository_with_a_remote_is_refused(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "memory.git"
    commit_memory(home, repo)
    git(repo, "remote", "add", "origin", "https://example.com/memory.git")
    (home / "memories" / "USER.md").write_text("changed\n")

    with pytest.raises(MemoryRepoError, match=r"has a remote; the coach's memory must stay"):
        commit_memory(home, repo)

    assert git(repo, "rev-list", "--count", "HEAD").strip() == "1"


@pytest.mark.parametrize("variable", ["GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL"])
def test_system_and_user_git_config_are_ignored(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Someone Else\n[commit]\n\tgpgSign = true\n")
    monkeypatch.setenv(variable, str(config))  # signing would fail: there is no key
    repo = tmp_path / "memory.git"

    assert commit_memory(home, repo) is not None
    assert git(repo, "log", "-1", "--format=%an").strip() == "hermes-trainer"


def test_an_existing_repository_is_kept(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "memory.git"
    first = commit_memory(home, repo)
    (home / "memories" / "USER.md").write_text("changed\n")

    second = commit_memory(home, repo)

    assert git(repo, "rev-parse", "HEAD~1").strip() == first
    assert git(repo, "rev-parse", "HEAD").strip() == second


def test_there_must_be_a_hermes_home(tmp_path: Path) -> None:
    with pytest.raises(MemoryRepoError, match=r"/missing is not a directory$"):
        commit_memory(tmp_path / "missing", tmp_path / "memory.git")

    assert not (tmp_path / "memory.git").exists()


def test_a_git_failure_is_reported(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "memory.git"
    repo.write_text("not a repository")

    with pytest.raises(MemoryRepoError, match=r"^git init failed: fatal: .+"):
        commit_memory(home, repo)


def test_the_failing_git_command_is_named(home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "memory.git"
    commit_memory(home, repo)
    (repo / "index").write_bytes(b"corrupt")

    with pytest.raises(MemoryRepoError, match=r"^git add failed: .+"):
        commit_memory(home, repo)


def test_git_must_be_installed(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(MemoryRepoError, match=r"^git is not installed$"):
        commit_memory(home, tmp_path / "memory.git")
