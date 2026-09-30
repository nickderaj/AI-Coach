"""``python -m trainer.api`` serves the app factory with uvicorn."""

import runpy
import sys
from dataclasses import dataclass, field
from typing import Any

import pytest

from trainer.api.__main__ import main


@dataclass
class FakeRun:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    def __call__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401  # why: mirrors uvicorn.run's open signature
        self.calls.append((args, kwargs))


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch) -> FakeRun:
    fake = FakeRun()
    monkeypatch.setattr("uvicorn.run", fake)
    return fake


EXPECTED = (
    ("trainer.api.app:create_app",),
    {
        "factory": True,
        "host": "127.0.0.1",
        "port": 8123,
        "proxy_headers": False,
        "server_header": False,
    },
)


def test_main_hands_the_factory_to_uvicorn(fake_run: FakeRun) -> None:
    main(["--host", "127.0.0.1", "--port", "8123"])

    assert fake_run.calls == [EXPECTED]


@pytest.mark.parametrize(
    ("argv", "missing"), [(["--host", "127.0.0.1"], "--port"), (["--port", "1"], "--host")]
)
def test_host_and_port_are_required(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str], argv: list[str], missing: str
) -> None:
    with pytest.raises(SystemExit):
        main(argv)

    assert f"the following arguments are required: {missing}" in capsys.readouterr().err
    assert fake_run.calls == []


def test_help(
    fake_run: FakeRun, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")  # argparse wraps help at the terminal width

    with pytest.raises(SystemExit):
        main(["--help"])

    out = capsys.readouterr().out
    assert out.startswith("usage: python -m trainer.api [-h] --host HOST --port PORT\n")
    assert "serve the API with uvicorn (used by the systemd unit)." in out
    assert fake_run.calls == []


def test_module_entry_point(fake_run: FakeRun, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["trainer.api", "--host", "127.0.0.1", "--port", "8123"])
    monkeypatch.delitem(sys.modules, "trainer.api.__main__", raising=False)

    runpy.run_module("trainer.api", run_name="__main__")

    assert fake_run.calls == [EXPECTED]
