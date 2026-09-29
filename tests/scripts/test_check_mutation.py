"""Mutation result checker."""

import io

import pytest

import check_mutation

KILLED = "    trainer.x.y__mutmut_1: killed\n"
SURVIVED = "    trainer.x.y__mutmut_2: survived\n"
TIMEOUT = "    trainer.x.y__mutmut_3: timeout\n"


def run_main(monkeypatch: pytest.MonkeyPatch, stdin: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return check_mutation.main()


def test_counts_mutants_and_reports_non_killed() -> None:
    total, problems = check_mutation.failures("noise\n" + KILLED + SURVIVED + TIMEOUT)

    assert total == 3
    assert problems == ["trainer.x.y__mutmut_2: survived", "trainer.x.y__mutmut_3: timeout"]


def test_all_killed_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, KILLED) == 0
    assert "1 mutants, all killed" in capsys.readouterr().out


def test_survivor_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, KILLED + SURVIVED) == 1
    assert "trainer.x.y__mutmut_2: survived" in capsys.readouterr().err


def test_missing_results_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, "no results here\n") == 1
    assert "did mutmut run" in capsys.readouterr().err
