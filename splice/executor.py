from __future__ import annotations

import ast
import builtins as _builtins
import inspect
import multiprocessing as mp
import signal
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Iterable, Optional

from .config import SpliceConfig
from .errors import ExecutionError, SandboxViolation


def _extract_expected_signature(signature_text: str) -> tuple[str, list[str]]:
    """Parse a Python signature string to (function_name, [param_names]).

    Example: "def add(a: int, b: int) -> int" -> ("add", ["a", "b"]).
    """

    try:
        sig = signature_text.strip()
        # Ensure there is a minimal body so the snippet parses as a function
        if sig.endswith(":"):
            snippet = sig + "\n    pass\n"
        else:
            snippet = sig + ":\n    pass\n"
        module = ast.parse(snippet)
    except SyntaxError as exc:  # pragma: no cover - validated earlier in pipeline
        raise ExecutionError(f"Invalid contract signature: {exc}") from exc

    fn_defs = [n for n in module.body if isinstance(n, ast.FunctionDef)]
    if not fn_defs:
        raise ExecutionError("Contract signature did not contain a function definition")
    fn = fn_defs[0]
    param_names: list[str] = []
    for arg in list(fn.args.posonlyargs) + list(fn.args.args):
        param_names.append(arg.arg)
    if fn.args.vararg is not None:
        param_names.append(fn.args.vararg.arg)
    for kw in fn.args.kwonlyargs:
        param_names.append(kw.arg)
    if fn.args.kwarg is not None:
        param_names.append(fn.args.kwarg.arg)
    return fn.name, param_names


def _build_restricted_builtins(*, allow_fs: bool) -> dict[str, Any]:
    """Construct a minimal builtins mapping for the sandbox.

    We expose a conservative subset of safe utilities. Dangerous entries like
    __import__, exec, eval, compile, open (unless allowed) are omitted.
    """

    safe_names = {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "callable",
        "chr",
        "complex",
        "dict",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hash",
        "hex",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "object",
        "ord",
        "pow",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
        "__build_class__",
    }

    allowed: dict[str, Any] = {name: getattr(_builtins, name) for name in safe_names if hasattr(_builtins, name)}

    # File system access via open is disallowed unless configured
    if allow_fs and hasattr(_builtins, "open"):
        allowed["open"] = getattr(_builtins, "open")

    return allowed


def _limited_import_factory(allowlist: set[str]) -> Callable[[str, Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[list[str]], int], ModuleType]:
    """Create a __import__ replacement that enforces an import allowlist."""

    import importlib  # local import inside sandbox

    def limited_import(name: str, globals: Optional[dict[str, Any]] = None, locals: Optional[dict[str, Any]] = None, fromlist: Optional[list[str]] = None, level: int = 0) -> ModuleType:  # type: ignore[override]
        root = name.split(".")[0]
        if root not in allowlist:
            raise SandboxViolation(f"Import of module '{root}' is not allowed")
        return importlib.import_module(name)

    return limited_import


def _preflight_ast_checks(code: str, *, allowlist: set[str], allow_fs: bool, allow_net: bool, allow_subprocess: bool) -> None:
    """Scan AST for disallowed imports and known-dangerous names.

    We fail fast on:
    - Imports of modules not in allowlist
    - References to '__import__', 'eval', 'exec'
    - Imports of common network/fs/subprocess modules if corresponding gates are disabled
    """

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ExecutionError(f"Generated code failed to parse: {exc}") from exc

    banned_names = {"__import__", "eval", "exec"}
    banned_modules_by_gate = {
        "fs": {"os", "pathlib", "io"},
        "net": {"socket", "httpx", "requests", "urllib", "ssl"},
        "subprocess": {"subprocess", "multiprocessing"},
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowlist:
                    raise SandboxViolation(f"Import of module '{root}' is not allowed by sandbox")
                if not allow_fs and root in banned_modules_by_gate["fs"]:
                    raise SandboxViolation(f"Import of filesystem-related module '{root}' is not allowed")
                if not allow_net and root in banned_modules_by_gate["net"]:
                    raise SandboxViolation(f"Import of networking module '{root}' is not allowed")
                if not allow_subprocess and root in banned_modules_by_gate["subprocess"]:
                    raise SandboxViolation(f"Import of subprocess module '{root}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            if root not in allowlist:
                raise SandboxViolation(f"Import from module '{root}' is not allowed by sandbox")
            if not allow_fs and root in banned_modules_by_gate["fs"]:
                raise SandboxViolation(f"Import of filesystem-related module '{root}' is not allowed")
            if not allow_net and root in banned_modules_by_gate["net"]:
                raise SandboxViolation(f"Import of networking module '{root}' is not allowed")
            if not allow_subprocess and root in banned_modules_by_gate["subprocess"]:
                raise SandboxViolation(f"Import of subprocess module '{root}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in banned_names:
                raise SandboxViolation(f"Use of '{node.id}' is not allowed in sandbox")


def _worker(code: str, signature_text: str, kwargs: dict[str, Any], cfg: SpliceConfig, conn) -> None:  # type: ignore[no-untyped-def]
    """Worker process entry point: execute user code in restricted env and return value via pipe."""

    try:
        allowlist = set(cfg.sandbox.allow_imports or [])
        allow_fs = bool(cfg.sandbox.allow_fs)
        allow_net = bool(cfg.sandbox.allow_net)
        allow_subprocess = bool(cfg.sandbox.allow_subprocess)

        _preflight_ast_checks(code, allowlist=allowlist, allow_fs=allow_fs, allow_net=allow_net, allow_subprocess=allow_subprocess)

        # Build globals with restricted builtins and pre-imported allowlist modules
        sandbox_builtins = _build_restricted_builtins(allow_fs=allow_fs)
        limited_import = _limited_import_factory(allowlist)
        sandbox_builtins["__import__"] = limited_import

        sandbox_globals: dict[str, Any] = {"__builtins__": sandbox_builtins}

        # Pre-import allowed modules to make them available without import lines
        for mod_name in sorted(allowlist):
            try:
                module = __import__(mod_name)
                sandbox_globals[mod_name] = module
                if mod_name == "numpy":
                    sandbox_globals["np"] = module
            except Exception:
                # If a module isn't installed, we skip; runtime code may still fail if it relies on it
                continue

        exec(code, sandbox_globals, sandbox_globals)

        expected_name, expected_params = _extract_expected_signature(signature_text)
        if expected_name not in sandbox_globals or not callable(sandbox_globals[expected_name]):
            raise ExecutionError(f"Function '{expected_name}' not found in generated code")

        fn: Callable[..., Any] = sandbox_globals[expected_name]
        sig = inspect.signature(fn)
        actual_params = [name for name in sig.parameters.keys()]
        if actual_params[: len(expected_params)] != expected_params:
            raise ExecutionError(
                f"Generated function parameters {actual_params} do not match contract {expected_params}"
            )

        result = fn(**kwargs)
        conn.send(("ok", result))
    except SandboxViolation as exc:
        conn.send(("sandbox", str(exc)))
    except Exception as exc:  # noqa: BLE001 - send back any failure
        conn.send(("error", f"{exc.__class__.__name__}: {exc}"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


@dataclass
class Executor:
    """Sandboxed child-process executor for generated code (Phase 4).

    Use run() to execute a generated function safely.
    """

    @staticmethod
    def run(
        code: str,
        signature: str,
        call_kwargs: dict[str, Any],
        config: SpliceConfig,
        *,
        timeout_seconds: float | None = 10.0,
    ) -> Any:
        """Execute generated function in a sandboxed child process and return the value.

        Raises SandboxViolation on disallowed operations, ExecutionError on runtime failures.
        """

        ctx = mp.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe()
        proc = ctx.Process(target=_worker, args=(code, signature, dict(call_kwargs), config, child_conn))
        proc.daemon = True
        proc.start()
        child_conn.close()

        try:
            if timeout_seconds is not None and timeout_seconds > 0:
                if not parent_conn.poll(timeout_seconds):
                    # Timeout - terminate process
                    try:
                        proc.kill()
                    except Exception:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                    raise ExecutionError("Execution timed out")
            msg_type, payload = parent_conn.recv()
            if msg_type == "ok":
                return payload
            if msg_type == "sandbox":
                raise SandboxViolation(str(payload))
            raise ExecutionError(str(payload))
        finally:
            try:
                parent_conn.close()
            except Exception:
                pass
            try:
                if proc.is_alive():
                    proc.terminate()
                proc.join(timeout=1.0)
            except Exception:
                pass


