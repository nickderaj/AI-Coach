"""``python -m trainer.mcp``: the stdio loop and its entry point."""

import io
import json
import runpy
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import override

import pytest

from trainer.mcp.__main__ import main, serve


@pytest.fixture
def data_dir(imported: sqlite3.Connection, tmp_path: Path) -> Path:
    imported.commit()
    return tmp_path


INITIALIZE = (
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}'
)
INITIALIZED = '{"jsonrpc":"2.0","method":"notifications/initialized"}'
CALL = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"recent_workouts"}}'


def test_serve_answers_each_request_on_its_own_line(data_dir: Path) -> None:
    out = io.StringIO()

    serve(
        [INITIALIZE + "\n", "\n", INITIALIZED + "\n", "  \n", CALL + "\n"],
        out,
        data_dir / "trainer.db",
    )

    lines = out.getvalue().split("\n")
    assert len(lines) == 3  # two answers, each ending in a newline
    assert lines[2] == ""
    assert json.loads(lines[0])["result"]["protocolVersion"] == "2025-11-25"
    answer = json.loads(lines[1])["result"]
    assert answer["isError"] is False
    assert len(json.loads(answer["content"][0]["text"])) == 2


def test_an_id_too_large_for_sqlite_does_not_stop_the_server(data_dir: Path) -> None:
    too_large = 2**63  # one past SQLite's largest INTEGER
    calls = [
        {"name": "get_workout", "arguments": {"workout_id": too_large}},
        {"name": "exercise_history", "arguments": {"exercise_id": too_large}},
    ]
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": params})
        for i, params in enumerate(calls, start=1)
    ]
    out = io.StringIO()

    serve([*lines, '{"jsonrpc":"2.0","id":3,"method":"ping"}'], out, data_dir / "trainer.db")

    first, second, third = (json.loads(line) for line in out.getvalue().splitlines())
    for answer, name in ((first, "workout_id"), (second, "exercise_id")):
        assert answer["result"]["isError"] is True
        assert answer["result"]["content"][0]["text"] == (
            f"invalid arguments: {name}: Input should be less than or equal to {too_large - 1}"
        )
    assert third == {"jsonrpc": "2.0", "id": 3, "result": {}}


class FlushCounter(io.StringIO):
    flushes = 0

    @override
    def flush(self) -> None:
        self.flushes += 1
        super().flush()


def test_every_answer_is_flushed_at_once(data_dir: Path) -> None:
    out = FlushCounter()

    serve([INITIALIZE, INITIALIZED, CALL], out, data_dir / "trainer.db")

    assert out.flushes == 2


def test_main_needs_the_data_directory(capsys: pytest.CaptureFixture[str]) -> None:
    assert main({}) == 2
    assert main({"TRAINER_DATA_DIR": ""}) == 2

    assert capsys.readouterr().err == "trainer.mcp: TRAINER_DATA_DIR must be set\n" * 2


def test_main_serves_stdin(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(CALL + "\n"))
    monkeypatch.setattr(sys, "stdout", out)

    assert main({"TRAINER_DATA_DIR": str(data_dir)}) == 0

    assert json.loads(out.getvalue())["id"] == 2


def test_main_reads_the_process_environment(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRAINER_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "stdin", io.StringIO(CALL + "\n"))
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    assert main() == 0


def test_the_module_runs_as_a_child_process(data_dir: Path) -> None:
    """How Hermes runs it: a child process speaking over its stdin and stdout."""
    done = subprocess.run(
        [sys.executable, "-m", "trainer.mcp"],
        input=f"{INITIALIZE}\n{INITIALIZED}\n{CALL}\n",
        capture_output=True,
        text=True,
        check=True,
        env={"TRAINER_DATA_DIR": str(data_dir)},
        timeout=20,
    )

    first, second = done.stdout.splitlines()
    assert json.loads(first)["id"] == 1
    assert json.loads(second)["result"]["isError"] is False


def test_module_entry_point_exits_with_main_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRAINER_DATA_DIR", raising=False)
    monkeypatch.delitem(sys.modules, "trainer.mcp.__main__", raising=False)

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("trainer.mcp", run_name="__main__")

    assert exited.value.code == 2
