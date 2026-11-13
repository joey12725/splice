from __future__ import annotations

from typing import Any

import pytest

from splice import ExecutionError, Executor, SandboxViolation, SpliceConfig


def _run(
    code: str, signature: str, kwargs: dict[str, Any] | None = None, cfg: SpliceConfig | None = None
):
    cfg = cfg or SpliceConfig()
    return Executor.run(code, signature, kwargs or {}, cfg, timeout_seconds=2.0)


def test_executor_runs_basic_function() -> None:
    code = "def add(a: int, b: int) -> int:\n    return a + b\n"
    out = _run(code, signature="def add(a: int, b: int) -> int:", kwargs={"a": 2, "b": 3})
    assert out == 5


def test_executor_blocks_disallowed_import() -> None:
    code = "import os\ndef foo() -> int:\n    return 1\n"
    with pytest.raises(SandboxViolation):
        _run(code, signature="def foo() -> int:")


def test_executor_allows_numpy_if_available() -> None:
    try:
        import numpy as np  # type: ignore
    except Exception:
        pytest.skip("numpy not installed")

    code = "import numpy as np\ndef total(a: numpy.ndarray) -> int:\n    return int(np.sum(a))\n"
    out = _run(
        code, signature="def total(a: numpy.ndarray) -> int:", kwargs={"a": np.array([1, 2, 3])}
    )
    assert out == 6


def test_executor_respects_fs_gate() -> None:
    code = (
        "def try_open() -> str:\n"
        "    f = open('somefile.txt', 'w')\n"
        "    try:\n"
        "        f.write('x')\n"
        "        return 'ok'\n"
        "    finally:\n"
        "        f.close()\n"
    )
    # Default config denies filesystem; using open should fail (no 'open' in builtins)
    with pytest.raises(ExecutionError):
        _run(code, signature="def try_open() -> str:")


def test_executor_timeout() -> None:
    code = "def spin() -> int:\n    while True:\n        pass\n"
    cfg = SpliceConfig()
    with pytest.raises(ExecutionError):
        Executor.run(code, "def spin() -> int:", {}, cfg, timeout_seconds=0.2)


def test_signature_mismatch_detected() -> None:
    code = "def add(x: int, y: int) -> int:\n    return x + y\n"
    with pytest.raises(ExecutionError):
        _run(code, signature="def add(a: int, b: int) -> int:", kwargs={"a": 1, "b": 2})


def test_execute_returns_captured_output_and_backend() -> None:
    code = (
        "def hello(name: str) -> str:\n    print('generating greeting')\n    return 'hi ' + name\n"
    )
    result = Executor.execute(code, "def hello(name: str) -> str", {"name": "ada"}, SpliceConfig())
    assert result.value == "hi ada"
    assert result.stdout.strip() == "generating greeting"
    assert result.backend in {"process", "seatbelt", "bubblewrap"}
    assert result.duration_ms > 0
