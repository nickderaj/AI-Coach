"""Repository policy checker.

Fixtures that would themselves trip the checker (tokens, suppressions, skipped
tests) are assembled from fragments so this file stays policy-clean.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

import policy_check
from policy_check import Violation

NOQA = "# no" + "qa: E501"
TYPE_IGNORE = "# type: " + "ignore[arg-type]"
WHY = "# " + "why: upstream stub is wrong"


def messages(violations: list[Violation]) -> list[str]:
    return [violation.message for violation in violations]


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestText:
    def test_clean_text_passes(self) -> None:
        assert policy_check.check_text("a.md", "nothing to see") == []

    def test_owner_path_is_rejected(self) -> None:
        text = "see " + "/home/" + "nick" + "/x"

        assert messages(policy_check.check_text("a.md", text)) == ["owner-specific absolute path"]

    @pytest.mark.parametrize(
        ("secret", "label"),
        [
            ("gh" + "o_" + "a" * 36, "GitHub token"),
            ("s" + "k-" + "b" * 24, "provider key"),
            ("8901490187" + ":AA" + "c" * 33, "Telegram bot token"),
            ("-----BEGIN " + "OPENSSH PRIVATE KEY-----", "private key"),
        ],
    )
    def test_secrets_are_rejected(self, secret: str, label: str) -> None:
        assert messages(policy_check.check_text("a.md", secret)) == [f"likely {label}"]

    def test_lockfiles_are_exempt_from_secret_patterns(self) -> None:
        secret = "s" + "k-" + "b" * 24

        assert policy_check.check_text("uv.lock", secret) == []


class TestPython:
    def test_justified_suppression_on_same_line_passes(self) -> None:
        assert policy_check.check_python("a.py", f"x = 1  {TYPE_IGNORE}  {WHY}\n") == []

    def test_justified_suppression_on_line_above_passes(self) -> None:
        assert policy_check.check_python("a.py", f"{WHY}\nx = 1  {NOQA}\n") == []

    def test_unjustified_suppression_is_rejected(self) -> None:
        found = policy_check.check_python("a.py", f"x = 1\ny = 2  {NOQA}\n")

        assert found == [Violation("a.py", 2, "suppression needs a '# why: ...' justification")]

    def test_suppression_on_first_line_without_reason_is_rejected(self) -> None:
        assert len(policy_check.check_python("a.py", f"x = 1  {TYPE_IGNORE}\n")) == 1

    @pytest.mark.parametrize(
        "line",
        [
            "@pytest.mark." + "skip(reason='later')",
            "@pytest.mark." + "xfail",
            "break" + "point()",
        ],
    )
    def test_skips_and_breakpoints_are_rejected(self, line: str) -> None:
        assert len(policy_check.check_python("a.py", line)) == 1


class TestTypeScript:
    @pytest.mark.parametrize(
        "line",
        [
            "it." + "only('x', () => {})",
            "describe." + "skip('x', () => {})",
            "// @ts-" + "ignore",
            "// eslint-" + "disable-next-line no-console",
        ],
    )
    def test_forbidden_constructs_are_rejected(self, line: str) -> None:
        assert len(policy_check.check_typescript("a.ts", line)) == 1

    def test_described_eslint_directive_passes(self) -> None:
        line = "// eslint-" + "disable-next-line no-console -- dev-only diagnostics"

        assert policy_check.check_typescript("a.ts", line) == []


class TestPins:
    def test_exact_python_pins_pass(self) -> None:
        text = (
            '[project]\ndependencies = ["fastapi==1.0.0"]\n'
            '[dependency-groups]\ndev = ["ruff==0.1.0", {include-group = "x"}]\n'
            '[build-system]\nrequires = ["hatchling==1.0"]\n'
        )

        assert policy_check.check_pyproject("pyproject.toml", text) == []

    def test_ranged_python_requirement_is_rejected(self) -> None:
        text = '[project]\ndependencies = ["fastapi>=1.0"]\n'

        assert len(policy_check.check_pyproject("pyproject.toml", text)) == 1

    def test_exact_npm_versions_pass(self) -> None:
        text = '{"dependencies": {"react": "19.3.0"}, "devDependencies": {"x": "1.0.0-rc.1"}}'

        assert policy_check.check_package_json("package.json", text) == []

    @pytest.mark.parametrize("version", ["^19.3.0", "~1.0.0", "*", "latest"])
    def test_ranged_npm_versions_are_rejected(self, version: str) -> None:
        text = f'{{"devDependencies": {{"react": "{version}"}}}}'

        assert len(policy_check.check_package_json("package.json", text)) == 1

    def test_pinned_workflow_passes(self) -> None:
        text = (
            "- uses: actions/checkout@" + "a" * 40 + "\n"
            "- uses: ./.github/actions/local\n"
            "- run: go run example.com/tool@" + "b" * 40 + "\n"
        )

        assert policy_check.check_workflow("w.yml", text) == []

    def test_tag_pinned_workflow_is_rejected(self) -> None:
        text = "- uses: actions/checkout@v4\n- run: go install example.com/tool@v1.2.3\n"

        assert len(policy_check.check_workflow("w.yml", text)) == 2


class TestPullRequestTitle:
    @pytest.mark.parametrize(
        "title",
        ["ci: add the quality gate", "feat(api)!: drop legacy route", "fix: `x` overflow"],
    )
    def test_conventional_titles_pass(self, title: str) -> None:
        assert policy_check.check_pr_title(title) == []

    @pytest.mark.parametrize(
        "title",
        ["Add stuff", "feat: Capitalised summary", "feature: x", "fix: " + "x" * 80],
    )
    def test_other_titles_are_rejected(self, title: str) -> None:
        assert len(policy_check.check_pr_title(title)) == 1


class TestRepository:
    def test_skipped_directories_and_binaries_are_ignored(self, tmp_path: Path) -> None:
        write(tmp_path, "node_modules/x.ts", "it." + "only('x')")
        (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00")

        assert policy_check.run(tmp_path, None) == []

    def test_git_work_tree_ignores_ignored_and_deleted_files(self, tmp_path: Path) -> None:
        git = shutil.which("git")
        assert git is not None
        subprocess.run([git, "init", "-q", str(tmp_path)], check=True)  # noqa: S603  # why: fixed argv
        write(tmp_path, ".gitignore", "coverage.xml\n")
        write(tmp_path, "coverage.xml", "/home/" + "nick/project")
        tracked = write(tmp_path, "kept.md", "fine")
        write(tmp_path, "untracked.md", "also checked")
        subprocess.run([git, "-C", str(tmp_path), "add", "kept.md"], check=True)  # noqa: S603  # why: fixed argv
        tracked.unlink()

        paths = policy_check.repository_paths(tmp_path)

        assert [path.name for path in paths] == [".gitignore", "untracked.md"]

    def test_git_work_tree_requires_git(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("shutil.which", lambda _: None)

        with pytest.raises(RuntimeError, match="git is required"):
            policy_check.repository_paths(tmp_path)

    def test_symlinks_are_rejected(self, tmp_path: Path) -> None:
        target = write(tmp_path, "a.md", "x")
        (tmp_path / "link.md").symlink_to(target)

        assert messages(policy_check.run(tmp_path, None)) == ["repository symlinks are prohibited"]

    def test_files_are_routed_to_their_checks(self, tmp_path: Path) -> None:
        write(tmp_path, "a.py", f"x = 1  {NOQA}\n")
        write(tmp_path, "b.tsx", "it." + "only('x')\n")
        write(tmp_path, "pyproject.toml", '[project]\ndependencies = ["x>=1"]\n')
        write(tmp_path, "web/package.json", '{"dependencies": {"x": "^1.0.0"}}')
        write(tmp_path, ".github/workflows/pr.yml", "- uses: a/b@v1\n")

        found = policy_check.run(tmp_path, "bad title")

        assert sorted({violation.path for violation in found}) == [
            ".github/workflows/pr.yml",
            "a.py",
            "b.tsx",
            "pull request title",
            "pyproject.toml",
            "web/package.json",
        ]

    def test_main_reports_success_and_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write(tmp_path, "ok.md", "fine")
        assert policy_check.main(["--root", str(tmp_path)]) == 0
        assert capsys.readouterr().out == "policy: ok\n"

        assert policy_check.main(["--root", str(tmp_path), "--pr-title", "nope"]) == 1
        assert "pull request title" in capsys.readouterr().err

    def test_violation_formats_with_and_without_line(self) -> None:
        assert str(Violation("a.py", 3, "m")) == "a.py:3: m"
        assert str(Violation("a.py", 0, "m")) == "a.py: m"
