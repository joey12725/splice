"""The examples double as smoke tests: they must run offline, end to end."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _run(script: str, *args: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [script, *args])
    monkeypatch.syspath_prepend(str(EXAMPLES))
    with pytest.raises(SystemExit) as info:
        runpy.run_path(str(EXAMPLES / script), run_name="__main__")
    assert info.value.code == 0


def test_quickstart(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _run("quickstart.py", monkeypatch=monkeypatch)
    out = capsys.readouterr().out
    assert "blend(4, 6)             -> 5.0" in out
    assert "model calls so far: 1" in out
    assert "credential grab         -> blocked" in out
    assert "harmonic(3, 6)          -> 4.0" in out


def test_calculator(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _run(
        "calculator_demo.py",
        "--offline",
        "--define",
        "hypot",
        "3?4",
        "6*7",
        "5?12",
        monkeypatch=monkeypatch,
    )
    out = capsys.readouterr().out
    assert "3?4 = 5.0" in out and "6*7 = 42.0" in out and "5?12 = 13.0" in out
