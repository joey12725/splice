from __future__ import annotations

import os
import re
from typing import Any, Callable

import pytest

from splice.client import OpenRouterClient
from splice.config import SpliceConfig, ModelConfig
from splice.prompt import PromptBundle, bundle_prompt
from splice.specs import Contracts, FunctionSpec
from splice.executor import Executor


pytestmark = pytest.mark.live


def _require_live() -> None:
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set; skipping live API tests")
    if os.getenv("SPLICE_RUN_LIVE_TESTS", "0") != "1":
        pytest.skip("Set SPLICE_RUN_LIVE_TESTS=1 to run live API tests")


def _make_spec(name: str, signature: str, inputs: dict[str, str], output: str, system_sig: str | None = None) -> FunctionSpec:
    contracts = Contracts(signature=signature, inputs=inputs, output=output, pydantic={})
    sys_prompt = f"Output exactly one Python function:\n{system_sig or signature}"  # stronger guidance
    return FunctionSpec(
        name=name,
        version="0.0.1",
        description=f"Live test for {name}",
        prompt="",
        system_prompt=sys_prompt,
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )


def _generate_code_text(spec: FunctionSpec, task_prompt: str) -> str:
    cfg = SpliceConfig(model=ModelConfig())
    bundle = bundle_prompt(spec, cfg, session_prompt=task_prompt)
    client = OpenRouterClient()
    return client.generate_code(bundle, cfg)


def _extract_function_name(signature: str) -> str:
    m = re.match(r"\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", signature)
    assert m, f"Invalid signature: {signature}"
    return m.group(1)


def _execute_with_sandbox(code: str, signature: str, kwargs: dict[str, Any] | None = None) -> Any:
    cfg = SpliceConfig()
    return Executor.run(code, signature, kwargs or {}, cfg)


def test_live_hello_world() -> None:
    _require_live()

    sig = "def hello() -> str:"
    spec = _make_spec("hello", sig, inputs={}, output="str", system_sig=sig)
    code = _generate_code_text(spec, task_prompt="Implement hello() returning 'hello world'.")

    out = _execute_with_sandbox(code, sig)
    assert isinstance(out, str)
    assert "hello" in out.lower()


def test_live_print_proxy() -> None:
    _require_live()

    sig = "def print_proxy(msg: str) -> str:"
    spec = _make_spec("print_proxy", sig, inputs={"msg": "str"}, output="str", system_sig=sig)
    code = _generate_code_text(spec, task_prompt="Return the same message; do not print.")

    msg = "Echo This"
    out = _execute_with_sandbox(code, sig, {"msg": msg})
    assert out == msg


def test_live_addition() -> None:
    _require_live()

    sig = "def add(a: int, b: int) -> int:"
    spec = _make_spec("add", sig, inputs={"a": "int", "b": "int"}, output="int", system_sig=sig)
    code = _generate_code_text(spec, task_prompt="Return the sum of a and b.")

    assert _execute_with_sandbox(code, sig, {"a": 2, "b": 3}) == 5
    assert _execute_with_sandbox(code, sig, {"a": -1, "b": 1}) == 0


def test_live_numpy_matmul() -> None:
    _require_live()
    try:
        import numpy as np  # type: ignore
    except Exception:
        pytest.skip("numpy not installed")

    sig = "def matmul(a: numpy.ndarray, b: numpy.ndarray) -> numpy.ndarray:"
    spec = _make_spec(
        "matmul",
        sig,
        inputs={"a": "numpy.ndarray", "b": "numpy.ndarray"},
        output="numpy.ndarray",
        system_sig=sig,
    )
    code = _generate_code_text(
        spec,
        task_prompt=(
            "Use numpy to return matrix multiplication of a and b."
        ),
    )

    a = np.array([[1, 2], [3, 4]])
    b = np.array([[5, 6], [7, 8]])
    out = _execute_with_sandbox(code, sig, {"a": a, "b": b})
    import numpy as np  # reaffirm type

    assert isinstance(out, np.ndarray)
    assert out.shape == (2, 2)
    assert (out == a @ b).all()


