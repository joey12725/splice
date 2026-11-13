"""Run generated functions inside a sandbox backend.

:class:`Executor` is the thin, synchronous front door used by
:class:`splice.Splice`. It parses the contract signature, builds a
:class:`~splice.sandbox.SandboxPolicy` from config, and hands the call to the
configured :class:`~splice.sandbox.Sandbox`. Generated code never runs in the
calling process.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from typing import Any

from .config import SpliceConfig
from .errors import ExecutionError
from .sandbox import (
    ExecutionRequest,
    ExecutionResult,
    Sandbox,
    create_sandbox,
    policy_from_config,
)


def parse_signature(signature_text: str) -> tuple[str, list[str]]:
    """Parse a contract signature into ``(function_name, [param_names])``.

    >>> parse_signature("def add(a: int, b: int) -> int")
    ('add', ['a', 'b'])
    """

    sig = signature_text.strip()
    snippet = (sig if sig.endswith(":") else sig + ":") + "\n    pass\n"
    try:
        module = ast.parse(snippet)
    except SyntaxError as exc:
        raise ExecutionError(f"Invalid contract signature: {exc}") from exc

    fn_defs = [n for n in module.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not fn_defs:
        raise ExecutionError("Contract signature did not contain a function definition")
    fn = fn_defs[0]
    params = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]]
    return fn.name, params


# Backwards-compatible alias for the pre-0.2 private helper.
_extract_expected_signature = parse_signature


class Executor:
    """Execute a generated function in the configured sandbox."""

    @staticmethod
    def execute(
        code: str,
        signature: str,
        call_kwargs: Mapping[str, Any],
        config: SpliceConfig,
        *,
        timeout_seconds: float | None = None,
        extra_sys_paths: Sequence[str] | None = None,
        sandbox: Sandbox | None = None,
    ) -> ExecutionResult:
        """Like :meth:`run`, but returns the full :class:`ExecutionResult`
        (value, captured stdout/stderr, duration and backend name)."""

        name, params = parse_signature(signature)
        backend = sandbox if sandbox is not None else create_sandbox(config.sandbox)
        policy = policy_from_config(
            config.sandbox,
            extra_sys_paths=tuple(extra_sys_paths or ()),
            timeout_seconds=timeout_seconds,
        )
        request = ExecutionRequest(
            code=code,
            function_name=name,
            expected_params=tuple(params),
            kwargs=dict(call_kwargs),
        )
        return backend.execute(request, policy)

    @staticmethod
    def run(
        code: str,
        signature: str,
        call_kwargs: Mapping[str, Any],
        config: SpliceConfig,
        *,
        timeout_seconds: float | None = None,
        extra_sys_paths: Sequence[str] | None = None,
        sandbox: Sandbox | None = None,
    ) -> Any:
        """Execute ``code`` and return the function's value.

        ``timeout_seconds`` overrides ``sandbox.timeout_seconds`` from config.
        Raises :class:`~splice.errors.SandboxViolation` for policy denials,
        :class:`~splice.errors.ResourceLimitExceeded` /
        :class:`~splice.errors.ExecutionTimeout` when a limit trips, and
        :class:`~splice.errors.ExecutionError` for runtime failures.
        """

        return Executor.execute(
            code,
            signature,
            call_kwargs,
            config,
            timeout_seconds=timeout_seconds,
            extra_sys_paths=extra_sys_paths,
            sandbox=sandbox,
        ).value
