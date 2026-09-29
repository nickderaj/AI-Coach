"""Runtime dependency licence checker."""

import io
from email.message import Message

import pytest

import check_licenses

EXPORT = "fastapi==0.1.0\n    # via hermes-trainer\nidna==3.0\n"


def package(*, expression: str | None = None, classifiers: tuple[str, ...] = ()) -> Message:
    message = Message()
    if expression is not None:
        message["License-Expression"] = expression
    for classifier in classifiers:
        message["Classifier"] = classifier
    return message


def test_pinned_packages_skips_comments() -> None:
    assert check_licenses.pinned_packages(EXPORT) == ["fastapi", "idna"]


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        (package(expression="MIT"), {"MIT"}),
        (package(expression="(Apache-2.0 OR BSD-3-Clause)"), {"Apache-2.0", "BSD-3-Clause"}),
        (
            package(classifiers=("License :: OSI Approved :: MIT License", "Topic :: Web")),
            {"MIT"},
        ),
        (
            package(classifiers=("License :: Other/Proprietary License",)),
            {"License :: Other/Proprietary License"},
        ),
        (package(), set()),
    ],
)
def test_licenses_reads_expression_then_classifiers(meta: Message, expected: set[str]) -> None:
    assert check_licenses.licenses(meta) == expected


def test_violations_flag_unknown_and_disallowed() -> None:
    metas = {
        "ok": package(expression="MIT"),
        "copyleft": package(expression="GPL-3.0-only"),
        "silent": package(),
    }

    found = check_licenses.violations(list(metas), metas.__getitem__)

    assert found == [
        "copyleft: GPL-3.0-only is not allow-listed",
        "silent: declares no recognisable licence",
    ]


def test_main_passes_on_the_installed_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("fastapi==0\n"))

    assert check_licenses.main() == 0
    assert "1 runtime packages" in capsys.readouterr().out


def test_main_fails_on_disallowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("x==1\n"))
    monkeypatch.setattr("importlib.metadata.metadata", lambda _: package(expression="GPL-3.0"))

    assert check_licenses.main() == 1
    assert "GPL-3.0 is not allow-listed" in capsys.readouterr().err


def test_main_fails_on_empty_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    assert check_licenses.main() == 1
    assert "no pinned packages" in capsys.readouterr().err
