"""``python -m trainer.push``: the sender's loop and making a VAPID key."""

import io
import json
import logging
import re
import runpy
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trainer.domain.notices import TEST_NOTICE
from trainer.push import __main__ as push_main
from trainer.push.__main__ import POLL_S, main, push_round, serve
from trainer.services.notices import PushOutcome, PushSender, post
from trainer.services.webpush import VapidKey, WebPushSender
from trainer.storage.database import connect, migrate
from trainer.storage.notices import Subscription, save_subscription

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
APPLE = "https://web.push.apple.com/QGuT8ar"


class FakeSender:
    """Answers every push with ``outcome``; records the payloads."""

    def __init__(self, outcome: PushOutcome = PushOutcome.DELIVERED) -> None:
        """Answer ``outcome``."""
        self.outcome = outcome
        self.payloads: list[bytes] = []

    def send(self, subscription: Subscription, payload: bytes) -> PushOutcome:  # noqa: ARG002  # why: the PushSender protocol
        self.payloads.append(payload)
        return self.outcome


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    with closing(connect(tmp_path / "trainer.db")) as conn:
        migrate(conn)
        save_subscription(conn, Subscription(APPLE, "BKey", "auth"), "t")
        conn.commit()
        post(conn, TEST_NOTICE, NOW)
    return tmp_path


def unsent(data_dir: Path) -> int:
    with closing(sqlite3.connect(data_dir / "trainer.db")) as conn:
        return int(conn.execute("SELECT count(*) FROM inbox WHERE sent_at IS NULL").fetchone()[0])


def test_a_round_pushes_what_is_due_and_logs_it(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sender = FakeSender()

    with caplog.at_level(logging.INFO, logger="trainer.push"):
        push_round(data_dir / "trainer.db", sender, NOW)
        push_round(data_dir / "trainer.db", sender, NOW)  # nothing left: nothing logged

    assert [json.loads(payload)["route"] for payload in sender.payloads] == ["#/inbox"]
    assert caplog.messages == ["pushed 1, failed 0, 0 subscriptions ended"]
    assert unsent(data_dir) == 0


@pytest.mark.parametrize(
    ("outcome", "logged"),
    [
        (PushOutcome.FAILED, "pushed 0, failed 1, 0 subscriptions ended"),
        (PushOutcome.GONE, "pushed 0, failed 0, 1 subscriptions ended"),
    ],
)
def test_a_round_logs_failures_and_ended_subscriptions(
    data_dir: Path, caplog: pytest.LogCaptureFixture, outcome: PushOutcome, logged: str
) -> None:
    with caplog.at_level(logging.INFO, logger="trainer.push"):
        push_round(data_dir / "trainer.db", FakeSender(outcome), NOW)

    assert caplog.messages == [logged]


def test_serve_pushes_every_poll_until_told_to_stop(data_dir: Path) -> None:
    waits: list[float] = []

    def wait(seconds: float) -> bool:
        waits.append(seconds)
        return len(waits) < 3

    serve(data_dir / "trainer.db", FakeSender(), wait, lambda: NOW)

    assert waits == [POLL_S] * 3
    assert POLL_S == 2.0
    assert unsent(data_dir) == 0


@pytest.fixture(autouse=True)
def app_logger() -> Iterator[logging.Logger]:
    """The app's logger, put back as it was afterwards: serving adds a handler to it."""
    app = logging.getLogger("trainer")
    handlers, level = list(app.handlers), app.level
    yield app
    app.handlers[:] = handlers
    app.setLevel(level)


def test_serve_builds_the_sender_from_the_environment(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, app_logger: logging.Logger
) -> None:
    key = VapidKey.generate()
    calls: list[tuple[Path, PushSender]] = []

    def fake_serve(database: Path, sender: PushSender, wait: object) -> None:  # noqa: ARG001  # why: serve's signature
        calls.append((database, sender))
        logging.getLogger("trainer.push").info("a round")
        logging.getLogger("trainer.push").debug("not shown")

    monkeypatch.setattr(push_main, "serve", fake_serve)
    env = {
        "TRAINER_DATA_DIR": str(data_dir),
        "TRAINER_VAPID_PRIVATE_KEY": key.text,
        "TRAINER_PUSH_CONTACT": "mailto:owner@example.com",
    }
    err = io.StringIO()
    monkeypatch.setattr("sys.stderr", err)

    assert main(["serve"], env=env) == 0

    ((database, sender),) = calls
    assert database == data_dir / "trainer.db"
    assert isinstance(sender, WebPushSender)
    assert sender._key.text == key.text  # noqa: SLF001  # why: checking the wiring
    assert sender._contact == "mailto:owner@example.com"  # noqa: SLF001  # why: as above
    assert err.getvalue() == "trainer.push: a round\n"
    assert app_logger.level == logging.INFO


def test_help(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit):
        main(["--help"])

    out = capsys.readouterr().out
    assert out.startswith("usage: python -m trainer.push [-h] {serve,new-key} ...\n")
    assert "push notices as they come due, or make a VAPID key." in out
    assert re.search(
        r"^ +serve +push notices as they come due \(the systemd unit\)$", out, re.MULTILINE
    )
    assert re.search(r"^ +new-key +print a new VAPID key pair as two env lines$", out, re.MULTILINE)


def test_serve_from_the_environment(data_dir: Path) -> None:
    env = {
        "TRAINER_DATA_DIR": str(data_dir),
        "TRAINER_VAPID_PRIVATE_KEY": VapidKey.generate().text,
        "TRAINER_PUSH_CONTACT": "mailto:owner@example.com",
    }
    with closing(connect(data_dir / "trainer.db")) as conn:
        conn.execute("DELETE FROM push_subscriptions")  # nothing to send to: no network
        conn.commit()
        fresh = post(conn, TEST_NOTICE, datetime.now(UTC) - timedelta(seconds=1))

    assert main(["serve"], env=env, wait=lambda _seconds: False) == 0

    with closing(sqlite3.connect(data_dir / "trainer.db")) as conn:
        sent = conn.execute("SELECT sent_at FROM inbox WHERE id = ?", (fresh,)).fetchone()[0]
    assert sent is not None  # the clock is the real one


@pytest.mark.parametrize(
    "missing", ["TRAINER_DATA_DIR", "TRAINER_VAPID_PRIVATE_KEY", "TRAINER_PUSH_CONTACT"]
)
def test_serve_needs_its_settings(
    data_dir: Path, missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {
        "TRAINER_DATA_DIR": str(data_dir),
        "TRAINER_VAPID_PRIVATE_KEY": VapidKey.generate().text,
        "TRAINER_PUSH_CONTACT": "mailto:owner@example.com",
        missing: "",
    }

    assert main(["serve"], env=env, wait=lambda _seconds: False) == 2

    assert capsys.readouterr().err == (
        "push: TRAINER_DATA_DIR, TRAINER_VAPID_PRIVATE_KEY, TRAINER_PUSH_CONTACT must be set\n"
    )
    assert unsent(data_dir) == 1


def test_the_default_wait_sleeps_and_goes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", slept.append)

    assert push_main._sleep(2.0) is True  # noqa: SLF001  # why: the production wait
    assert slept == [2.0]


def test_new_key_prints_a_pair(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["new-key"]) == 0

    lines = capsys.readouterr().out.splitlines()
    names = [line.partition("=")[0] for line in lines]
    assert names == ["TRAINER_VAPID_PRIVATE_KEY", "TRAINER_VAPID_PUBLIC_KEY"]
    key = VapidKey.from_text(lines[0].partition("=")[2])
    assert lines[1] == f"TRAINER_VAPID_PUBLIC_KEY={key.public_text}"


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main([])

    assert "the following arguments are required: command" in capsys.readouterr().err


def test_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["trainer.push", "new-key"])
    monkeypatch.delitem(sys.modules, "trainer.push.__main__", raising=False)

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("trainer.push", run_name="__main__")

    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith("TRAINER_VAPID_PRIVATE_KEY=")
