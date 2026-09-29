"""Coverage contract checker."""

import json
from pathlib import Path
from typing import Any

import pytest

import check_coverage

MARKER = "# coverage-" + "critical"
SOURCE = f"""\
def plain():
    return 1


{MARKER}
@decorator

def critical(x):
    if x:
        return 1
    return 2
"""


def report(
    *, total: float = 100.0, module: float = 100.0, missing_branches: list[list[int]] | None = None
) -> dict[str, Any]:
    return {
        "meta": {"branch_coverage": True},
        "totals": {"percent_covered": total},
        "files": {
            "src/m.py": {
                "summary": {"percent_covered": module},
                "functions": {
                    "plain": {"start_line": 1, "missing_lines": [], "missing_branches": []},
                    "critical": {
                        "start_line": 8,
                        "missing_lines": [],
                        "missing_branches": missing_branches or [],
                    },
                },
            }
        },
    }


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def test_fully_covered_report_passes(root: Path) -> None:
    assert check_coverage.check(report(), root) == []


def test_low_total_and_module_fail(root: Path) -> None:
    failures = check_coverage.check(report(total=89.9, module=84.9), root)

    assert failures == [
        "total coverage 89.90% is below 90.0%",
        "src/m.py: 84.90% is below 85.0%",
    ]


def test_critical_function_with_missing_branch_fails(root: Path) -> None:
    failures = check_coverage.check(report(missing_branches=[[9, 11]]), root)

    assert failures == [
        "src/m.py:8: critical function critical is missing lines [] and branches [[9, 11]]"
    ]


def test_marker_resolves_through_decorators_and_blank_lines(root: Path) -> None:
    found = check_coverage.critical_functions(root, ["src/m.py"])

    assert found == [check_coverage.CriticalFunction("src/m.py", 8)]


def test_marker_without_function_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(f"{MARKER}\nx = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="is not above a function"):
        check_coverage.critical_functions(tmp_path, ["m.py"])


def test_marker_at_end_of_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(f"{MARKER}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="is not above a function"):
        check_coverage.critical_functions(tmp_path, ["m.py"])


def test_unmeasured_critical_function_fails(root: Path) -> None:
    data = report()
    del data["files"]["src/m.py"]["functions"]["critical"]

    assert check_coverage.check(data, root) == ["src/m.py:8: critical function not measured"]


def run_main(tmp_path: Path, root: Path, data: dict[str, Any]) -> int:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return check_coverage.main([str(path), "--root", str(root)])


def test_main_passes_and_fails(
    tmp_path: Path, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(tmp_path, root, report()) == 0
    assert capsys.readouterr().out == "coverage: ok (100.00%)\n"

    assert run_main(tmp_path, root, report(total=1.0)) == 1
    assert "total coverage" in capsys.readouterr().err


def test_main_requires_branch_coverage(tmp_path: Path, root: Path) -> None:
    data = report()
    data["meta"]["branch_coverage"] = False

    assert run_main(tmp_path, root, data) == 1


def test_main_reports_bad_markers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text(f"{MARKER}\n", encoding="utf-8")

    assert run_main(tmp_path, tmp_path, report()) == 1
    assert "is not above a function" in capsys.readouterr().err
