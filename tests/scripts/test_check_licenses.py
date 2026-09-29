"""Runtime dependency licence checker (Python and pnpm)."""

import io
import json
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


def pnpm_report(**groups: list[str]) -> str:
    return json.dumps(
        {expression: [{"name": name} for name in names] for expression, names in groups.items()}
    )


def run_main(monkeypatch: pytest.MonkeyPatch, stdin: str, *args: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return check_licenses.main(list(args))


def test_pinned_packages_skips_comments() -> None:
    assert check_licenses.pinned_packages(EXPORT) == ["fastapi", "idna"]


def test_spdx_identifiers_split_compound_expressions() -> None:
    assert check_licenses.spdx_identifiers("(MIT OR Apache-2.0) AND ISC") == {
        "MIT",
        "Apache-2.0",
        "ISC",
    }


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


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ({"MIT"}, None),
        ({"GPL-3.0-only"}, "x: GPL-3.0-only is not allow-listed"),
        (set(), "x: declares no recognisable licence"),
    ],
)
def test_violation(declared: set[str], expected: str | None) -> None:
    assert check_licenses.violation("x", declared) == expected


def test_python_packages_flag_unknown_and_disallowed() -> None:
    metas = {
        "ok": package(expression="MIT"),
        "copyleft": package(expression="GPL-3.0-only"),
        "silent": package(),
    }
    export = "".join(f"{name}==1\n" for name in metas)

    names, found = check_licenses.python_packages(export, metas.__getitem__)

    assert names == ["ok", "copyleft", "silent"]
    assert found == [
        "copyleft: GPL-3.0-only is not allow-listed",
        "silent: declares no recognisable licence",
    ]


def test_pnpm_packages_group_by_declared_licence() -> None:
    report = pnpm_report(**{"MIT": ["react"], "(MIT OR GPL-2.0)": ["dual"], "Unknown": ["odd"]})

    names, found = check_licenses.pnpm_packages(report)

    assert sorted(names) == ["dual", "odd", "react"]
    assert found == [
        "dual: GPL-2.0 is not allow-listed",
        "odd: Unknown is not allow-listed",
    ]


def test_pnpm_packages_accept_empty_output() -> None:
    assert check_licenses.pnpm_packages("  \n") == ([], [])


def test_main_passes_on_the_installed_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, "fastapi==0\n") == 0
    assert "1 runtime packages" in capsys.readouterr().out


def test_main_pnpm_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, pnpm_report(MIT=["react", "react-dom"]), "--pnpm") == 0
    assert "2 runtime packages" in capsys.readouterr().out


def test_main_fails_on_disallowed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("importlib.metadata.metadata", lambda _: package(expression="GPL-3.0"))

    assert run_main(monkeypatch, "x==1\n") == 1
    assert "GPL-3.0 is not allow-listed" in capsys.readouterr().err


def test_main_fails_on_empty_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(monkeypatch, "") == 1
    assert "no packages on stdin" in capsys.readouterr().err
