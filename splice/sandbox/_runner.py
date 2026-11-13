"""Child-side bootstrap that runs inside every sandbox backend.

This file is shipped verbatim into the sandbox (copied into the private working
directory, or passed with ``python -c`` for container backends), so it must stay
standard-library only and must not import anything from ``splice``.

The parent process imports it too, but only for the value codec
(:func:`encode_value` / :func:`decode_value`). Importing it has no side effects.

Protocol
--------
* The parent writes one JSON request to the child's stdin and closes it.
* The child writes exactly one line, ``<nonce> <json-response>``, to fd 1.
  Anything the generated code prints is captured and returned in the response,
  so stray output can never be confused with the result.

Values cross the boundary as tagged JSON, never pickle: the parent must not
deserialize anything that could execute code.
"""

from __future__ import annotations

import ast
import base64
import builtins
import datetime as _dt
import decimal
import errno
import fractions
import importlib
import io
import json
import math
import os
import sys
import types
import uuid
from collections.abc import Callable
from typing import Any

PROTOCOL_VERSION = 1

# --------------------------------------------------------------------------- #
# Value codec (used on both sides of the boundary)
# --------------------------------------------------------------------------- #

TAG = "$splice"
MAX_DEPTH = 100
_NUMPY_SAFE_KINDS = frozenset("biufcUS")


def encode_value(value: Any, _depth: int = 0) -> Any:
    """Encode ``value`` as JSON-compatible data with explicit type tags.

    Supported: None, bool, int, float (including nan/inf), str, bytes, bytearray,
    list, tuple, dict (any hashable keys), set, frozenset, complex, Decimal,
    Fraction, datetime/date/time/timedelta, UUID, and numpy arrays/scalars.
    """

    if _depth > MAX_DEPTH:
        raise TypeError("value is nested too deeply to cross the sandbox boundary")
    d = _depth + 1
    if value is None or isinstance(value, (bool, str)):
        return value if type(value) in (bool, str, type(None)) else _plain(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return {TAG: "float", "v": repr(float(value))}
        return float(value)
    if isinstance(value, list):
        return [encode_value(v, d) for v in value]
    if isinstance(value, tuple):
        return {TAG: "tuple", "v": [encode_value(v, d) for v in value]}
    if isinstance(value, dict):
        if TAG not in value and all(type(k) is str for k in value):
            return {k: encode_value(v, d) for k, v in value.items()}
        pairs = [[encode_value(k, d), encode_value(v, d)] for k, v in value.items()]
        return {TAG: "dict", "v": pairs}
    if isinstance(value, frozenset):
        return {TAG: "frozenset", "v": [encode_value(v, d) for v in value]}
    if isinstance(value, set):
        return {TAG: "set", "v": [encode_value(v, d) for v in value]}
    if isinstance(value, (bytes, bytearray)):
        kind = "bytearray" if isinstance(value, bytearray) else "bytes"
        return {TAG: kind, "v": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, complex):
        return {TAG: "complex", "v": [encode_value(value.real, d), encode_value(value.imag, d)]}
    if isinstance(value, decimal.Decimal):
        return {TAG: "decimal", "v": str(value)}
    if isinstance(value, fractions.Fraction):
        return {TAG: "fraction", "v": [value.numerator, value.denominator]}
    if isinstance(value, _dt.datetime):
        return {TAG: "datetime", "v": value.isoformat()}
    if isinstance(value, _dt.date):
        return {TAG: "date", "v": value.isoformat()}
    if isinstance(value, _dt.time):
        return {TAG: "time", "v": value.isoformat()}
    if isinstance(value, _dt.timedelta):
        return {TAG: "timedelta", "v": [value.days, value.seconds, value.microseconds]}
    if isinstance(value, uuid.UUID):
        return {TAG: "uuid", "v": str(value)}
    if type(value).__module__ == "numpy" and hasattr(value, "dtype") and hasattr(value, "tolist"):
        if getattr(value, "ndim", 0) == 0:
            return encode_value(value.item(), _depth)
        return {
            TAG: "ndarray",
            "dtype": str(value.dtype),
            "v": encode_value(value.tolist(), d),
        }
    raise TypeError(f"values of type {type(value).__name__!r} cannot cross the sandbox boundary")


def _plain(value: Any) -> Any:
    # str/bool subclasses are flattened to the builtin type.
    if isinstance(value, bool):
        return bool(value)
    return str(value)


def decode_value(data: Any, _depth: int = 0) -> Any:
    """Inverse of :func:`encode_value`. Only ever constructs known, inert types."""

    if _depth > MAX_DEPTH:
        raise ValueError("encoded value is nested too deeply")
    d = _depth + 1
    if data is None or isinstance(data, (bool, int, float, str)):
        return data
    if isinstance(data, list):
        return [decode_value(v, d) for v in data]
    if not isinstance(data, dict):
        raise ValueError(f"unexpected encoded value of type {type(data).__name__}")
    if TAG not in data:
        return {str(k): decode_value(v, d) for k, v in data.items()}

    tag = data[TAG]
    v: Any = data.get("v")
    if tag == "float":
        if v not in ("nan", "inf", "-inf"):
            raise ValueError("invalid float payload")
        return float(v)
    if tag == "tuple":
        return tuple(decode_value(x, d) for x in v)
    if tag == "dict":
        return {decode_value(k, d): decode_value(x, d) for k, x in v}
    if tag == "set":
        return {decode_value(x, d) for x in v}
    if tag == "frozenset":
        return frozenset(decode_value(x, d) for x in v)
    if tag == "bytes":
        return base64.b64decode(v)
    if tag == "bytearray":
        return bytearray(base64.b64decode(v))
    if tag == "complex":
        return complex(decode_value(v[0], d), decode_value(v[1], d))
    if tag == "decimal":
        return decimal.Decimal(v)
    if tag == "fraction":
        return fractions.Fraction(int(v[0]), int(v[1]))
    if tag == "datetime":
        return _dt.datetime.fromisoformat(v)
    if tag == "date":
        return _dt.date.fromisoformat(v)
    if tag == "time":
        return _dt.time.fromisoformat(v)
    if tag == "timedelta":
        return _dt.timedelta(days=int(v[0]), seconds=int(v[1]), microseconds=int(v[2]))
    if tag == "uuid":
        return uuid.UUID(v)
    if tag == "ndarray":
        items = decode_value(v, d)
        try:
            import numpy as np
        except ImportError:
            return items
        dtype = np.dtype(str(data.get("dtype", "float64")))
        if dtype.kind not in _NUMPY_SAFE_KINDS:
            return np.array(items)
        return np.array(items, dtype=dtype)
    raise ValueError(f"unknown value tag {tag!r}")


# --------------------------------------------------------------------------- #
# Language-level guard (restricted Python)
# --------------------------------------------------------------------------- #


class SandboxDenied(PermissionError):
    """Raised inside the sandbox when code attempts a disallowed operation."""


FS_MODULES = frozenset({"os", "pathlib", "io", "shutil", "tempfile", "glob", "fileinput"})
NET_MODULES = frozenset(
    {"socket", "ssl", "http", "urllib", "httpx", "requests", "ftplib", "smtplib", "asyncio"}
)
PROC_MODULES = frozenset({"subprocess", "multiprocessing", "pty", "signal", "concurrent"})
ALWAYS_DENIED_MODULES = frozenset(
    {
        "ctypes",
        "_ctypes",
        "cffi",
        "gc",
        "inspect",
        "sys",
        "builtins",
        "importlib",
        "marshal",
        "pickle",
        "code",
        "codeop",
        "runpy",
        "__main__",
    }
)

_BANNED_NAMES = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "compile",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "breakpoint",
        "input",
        "help",
        "__builtins__",
        "__loader__",
        "__spec__",
    }
)
_SAFE_DUNDERS = frozenset({"__name__", "__doc__", "__qualname__", "__module__", "__init__"})
_BANNED_ATTRS = frozenset(
    {
        "f_globals",
        "f_locals",
        "f_back",
        "f_builtins",
        "f_code",
        "tb_frame",
        "gi_frame",
        "gi_code",
        "cr_frame",
        "cr_code",
        "ag_frame",
        "ag_code",
        "co_code",
        "mro",
    }
)

_SAFE_BUILTINS = (
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "complex",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "hasattr",
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
    "oct",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
    "__build_class__",
    "True",
    "False",
    "None",
    "NotImplemented",
    "Ellipsis",
)
_SAFE_EXCEPTIONS = (
    "BaseException",
    "Exception",
    "ArithmeticError",
    "AssertionError",
    "AttributeError",
    "FloatingPointError",
    "IndexError",
    "KeyError",
    "LookupError",
    "NotImplementedError",
    "OverflowError",
    "RecursionError",
    "RuntimeError",
    "StopIteration",
    "TypeError",
    "UnicodeError",
    "ValueError",
    "ZeroDivisionError",
    "ArithmeticError",
)


def _module_gate(root: str, policy: dict[str, Any]) -> str | None:
    """Return a denial reason for importing top-level module ``root``, or None."""

    allow = set(policy.get("allow_imports") or [])
    if root in ALWAYS_DENIED_MODULES and root not in allow:
        return f"import of module '{root}' is not allowed"
    if root not in allow:
        return f"import of module '{root}' is not in sandbox.allow_imports"
    if root in FS_MODULES and not policy.get("allow_fs"):
        return f"import of filesystem module '{root}' requires sandbox.allow_fs"
    if root in NET_MODULES and not policy.get("allow_net"):
        return f"import of networking module '{root}' requires sandbox.allow_net"
    if root in PROC_MODULES and not policy.get("allow_subprocess"):
        return f"import of process module '{root}' requires sandbox.allow_subprocess"
    return None


def check_source(code: str, policy: dict[str, Any]) -> None:
    """Static checks on generated source. Raises SandboxDenied or SyntaxError."""

    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                reason = _module_gate(alias.name.split(".")[0], policy)
                if reason:
                    raise SandboxDenied(reason)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise SandboxDenied("relative imports are not allowed")
            reason = _module_gate((node.module or "").split(".")[0], policy)
            if reason:
                raise SandboxDenied(reason)
        elif isinstance(node, ast.Name):
            if node.id in _BANNED_NAMES:
                raise SandboxDenied(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__") and attr not in _SAFE_DUNDERS:
                raise SandboxDenied(f"access to dunder attribute '{attr}' is not allowed")
            if attr in _BANNED_ATTRS:
                raise SandboxDenied(f"access to attribute '{attr}' is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            continue


def _module_view(module: types.ModuleType, allow: frozenset[str]) -> Any:
    """Wrap a module so generated code cannot walk to modules outside the allowlist.

    ``statistics.sys.modules['os']`` is the classic escape from import
    allowlists; the view refuses to hand out any module attribute whose root
    package is not allowed. The wrapped module lives in a closure, which the
    AST guard keeps out of reach (no dunder access).
    """

    def _get(self: Any, name: str) -> Any:
        if name.startswith("__") and name.endswith("__") and name not in _SAFE_DUNDERS:
            raise AttributeError(name)
        value = getattr(module, name)
        if isinstance(value, types.ModuleType):
            root = value.__name__.split(".")[0]
            if root not in allow:
                raise SandboxDenied(f"access to module '{value.__name__}' is not allowed")
            return _module_view(value, allow)
        return value

    def _set(self: Any, name: str, value: Any) -> None:
        raise SandboxDenied("modules are read-only inside the sandbox")

    def _dir(self: Any) -> list[str]:
        return [n for n in dir(module) if not n.startswith("_")]

    def _repr(self: Any) -> str:
        return f"<module '{module.__name__}' (sandboxed)>"

    view_type = type(
        "module",
        (),
        {
            "__slots__": (),
            "__getattr__": _get,
            "__setattr__": _set,
            "__delattr__": _set,
            "__dir__": _dir,
            "__repr__": _repr,
        },
    )
    return view_type()


def _restricted_namespace(policy: dict[str, Any]) -> dict[str, Any]:
    allow = frozenset(policy.get("allow_imports") or [])
    safe: dict[str, Any] = {}
    for name in _SAFE_BUILTINS + _SAFE_EXCEPTIONS:
        if hasattr(builtins, name):
            safe[name] = getattr(builtins, name)
    if policy.get("allow_fs"):
        safe["open"] = builtins.open

    def limited_import(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if level:
            raise SandboxDenied("relative imports are not allowed")
        reason = _module_gate(name.split(".")[0], policy)
        if reason:
            raise SandboxDenied(reason)
        importlib.import_module(name)
        target = name if fromlist else name.split(".")[0]
        return _module_view(sys.modules[target], allow)

    safe["__import__"] = limited_import
    namespace: dict[str, Any] = {"__builtins__": safe, "__name__": "splice_generated"}

    for mod_name in sorted(allow):
        if _module_gate(mod_name, policy):
            continue
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            continue
        namespace[mod_name.split(".")[0]] = _module_view(module, allow)
        if mod_name == "numpy":
            namespace["np"] = namespace["numpy"]
    return namespace


# --------------------------------------------------------------------------- #
# Process-level guard (audit hook) and resource limits
# --------------------------------------------------------------------------- #

_PROCESS_EVENTS = frozenset(
    {
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
        "os.startfile",
        "os.kill",
        "os.killpg",
        "subprocess.Popen",
        "pty.spawn",
        "signal.pthread_kill",
        "_posixsubprocess.fork_exec",
    }
)
_NET_EVENTS_PREFIXES = (
    "socket.",
    "urllib.Request",
    "http.client.",
    "ftplib.",
    "smtplib.",
    "poplib.",
    "imaplib.",
    "nntplib.",
    "telnetlib.",
    "webbrowser.",
)
_FS_PATH_EVENTS = frozenset(
    {
        "os.remove",
        "os.rmdir",
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "os.utime",
        "os.chflags",
        "os.lchflags",
        "os.setxattr",
        "os.removexattr",
        "os.chdir",
        "shutil.rmtree",
        "shutil.chown",
        "shutil.make_archive",
        "shutil.unpack_archive",
    }
)
_FS_TWO_PATH_EVENTS = frozenset(
    {
        "os.rename",
        "shutil.copyfile",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.copytree",
        "shutil.move",
    }
)
_PROCESS_IMPORTS = frozenset(
    {
        "_posixsubprocess",
        "multiprocessing.popen_fork",
        "multiprocessing.popen_spawn_posix",
        "multiprocessing.popen_forkserver",
    }
)
_LISTING_EVENTS = frozenset(
    {"os.listdir", "os.scandir", "glob.glob", "glob.glob/2", "os.listxattr", "os.getxattr"}
)
_ALWAYS_DENIED_EVENTS = frozenset(
    {
        "os.symlink",
        "os.link",
        "sys.addaudithook",
        "sys._getframe",
        "sys._current_frames",
        "sys._current_exceptions",
        "resource.setrlimit",
        "resource.prlimit",
        "sys.setprofile",
        "sys.settrace",
        "sys.monitoring.register_callback",
        "os.setns",
        "os.unshare",
    }
)
_FRAME_ATTRS = frozenset({"tb_frame", "gi_frame", "cr_frame", "ag_frame", "f_back"})
_WRITE_FLAGS = (
    getattr(os, "O_WRONLY", 1)
    | getattr(os, "O_RDWR", 2)
    | getattr(os, "O_CREAT", 0)
    | getattr(os, "O_TRUNC", 0)
    | getattr(os, "O_APPEND", 0)
)


def _under(path: str, roots: tuple[str, ...]) -> bool:
    return any(path == root or path.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _resolve(path: Any) -> str | None:
    if isinstance(path, int):
        return None
    try:
        return os.path.realpath(os.fsdecode(path))
    except Exception:
        return ""


def make_audit_hook(
    policy: dict[str, Any], workdir: str, read_roots: tuple[str, ...], denials: list[str]
) -> Callable[[str, tuple[Any, ...]], None]:
    """Build the ``sys.addaudithook`` callback that enforces fs/net/process policy.

    Every decision depends only on immutable values captured here, so code
    running after installation has no switch to flip.
    """

    allow_fs = bool(policy.get("allow_fs"))
    allow_net = bool(policy.get("allow_net"))
    allow_proc = bool(policy.get("allow_subprocess"))
    work = (os.path.realpath(workdir),)
    record = denials.append

    def deny(reason: str) -> None:
        record(reason)
        raise SandboxDenied(f"splice sandbox: {reason}")

    def writable(path: str | None) -> bool:
        return allow_fs and path is not None and _under(path, work)

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open":
            path = _resolve(args[0])
            if path is None:
                return
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            if isinstance(mode, str):
                write = any(c in mode for c in "wax+")
            else:
                write = bool((flags or 0) & _WRITE_FLAGS)
            if writable(path):
                return
            if not write and _under(path, read_roots):
                return
            deny(f"filesystem access denied: {os.fsdecode(args[0])}")
        elif event in _LISTING_EVENTS:
            raw = args[0] if args else "."
            path = _resolve("." if raw is None else raw)
            if path is None or writable(path) or _under(path, read_roots):
                return
            deny(f"directory listing denied: {raw}")
        elif event in _FS_PATH_EVENTS:
            path = _resolve(args[0]) if args else ""
            if not writable(path):
                deny(f"filesystem modification denied ({event})")
        elif event in _FS_TWO_PATH_EVENTS:
            if not all(writable(_resolve(a)) for a in args[:2]):
                deny(f"filesystem modification denied ({event})")
        elif event in _PROCESS_EVENTS:
            if not allow_proc:
                deny(f"process creation denied ({event})")
        elif event == "import":
            # _posixsubprocess.fork_exec raises no audit event of its own.
            if not allow_proc and args and args[0] in _PROCESS_IMPORTS:
                deny(f"process creation denied (import {args[0]})")
        elif event.startswith(_NET_EVENTS_PREFIXES):
            if not allow_net:
                deny(f"network access denied ({event})")
        elif event.startswith("ctypes.") or event.startswith("gc."):
            deny(f"low-level introspection denied ({event})")
        elif event in _ALWAYS_DENIED_EVENTS:
            deny(f"operation denied ({event})")
        elif event == "object.__getattr__" and len(args) > 1 and args[1] in _FRAME_ATTRS:
            deny("frame introspection denied")

    return hook


def apply_limits(limits: dict[str, Any]) -> None:
    """Apply POSIX resource limits to the current process (best effort per platform)."""

    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return

    def setlimit(which: str, soft: int, hard: int | None = None) -> None:
        res = getattr(resource, which, None)
        if res is None:
            return
        try:
            cur_soft, cur_hard = resource.getrlimit(res)
            new_hard = hard if hard is not None else soft
            if cur_hard != resource.RLIM_INFINITY:
                new_hard = min(new_hard, cur_hard)
            resource.setrlimit(res, (min(soft, new_hard), new_hard))
        except (ValueError, OSError):
            # macOS rejects RLIMIT_AS; the parent enforces memory with a watchdog.
            pass

    cpu = int(limits.get("cpu_seconds") or 0)
    if cpu > 0:
        setlimit("RLIMIT_CPU", cpu, cpu + 1)
    mem_mb = int(limits.get("memory_mb") or 0)
    if mem_mb > 0 and sys.platform.startswith("linux"):
        setlimit("RLIMIT_AS", mem_mb * 1024 * 1024)
    fsize_mb = limits.get("max_file_size_mb")
    if fsize_mb is not None:
        setlimit("RLIMIT_FSIZE", int(fsize_mb) * 1024 * 1024)
    nofile = int(limits.get("max_open_files") or 0)
    if nofile > 0:
        setlimit("RLIMIT_NOFILE", nofile)
    setlimit("RLIMIT_CORE", 0)


def deny_new_processes() -> None:
    """Set RLIMIT_NPROC to zero so fork()/clone() fail with EAGAIN.

    NPROC is accounted per user, so any value below the user's current process
    count blocks process creation outright. Called after imports so numerical
    libraries can finish starting their worker threads.
    """

    try:
        import resource

        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


class _CappedText(io.StringIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit
        self._size = 0

    def write(self, s: str) -> int:
        n = len(s)
        room = self._limit - self._size
        if room > 0:
            super().write(s[:room])
        self._size += n
        return n


def _read_roots(extra: list[str]) -> tuple[str, ...]:
    """Directories the code may read: the interpreter install and its site-packages.

    Deliberately *not* every ``sys.path`` entry: editable installs add project
    roots through ``.pth`` files, and a project root can hold ``.env`` files.
    """

    import site
    import sysconfig

    candidates = [sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]
    candidates += [p for p in site.getsitepackages() if p]
    paths = sysconfig.get_paths()
    candidates += [paths.get(k, "") for k in ("stdlib", "platstdlib", "purelib", "platlib")]
    candidates += [p for p in sys.path if p.endswith(".zip")]
    candidates += extra
    candidates += ["/usr/share/zoneinfo", "/dev/null", "/dev/urandom"]
    roots: list[str] = []
    for c in candidates:
        if not c:
            continue
        try:
            r = os.path.realpath(c)
        except Exception:
            continue
        if r and r != os.sep and r not in roots:
            roots.append(r)
    return tuple(roots)


def _prune_sys_path(roots: tuple[str, ...]) -> None:
    """Drop import paths outside the read roots so finders never touch them."""

    sys.path[:] = [p for p in sys.path if p and _under(os.path.realpath(p), roots)]


def _run(req: dict[str, Any], workdir: str) -> dict[str, Any]:
    policy: dict[str, Any] = req.get("policy") or {}
    limits: dict[str, Any] = req.get("limits") or {}
    restricted = bool(policy.get("restricted_python", True))
    allow_proc = bool(policy.get("allow_subprocess"))

    apply_limits(limits)
    for p in reversed(req.get("sys_path") or []):
        if p not in sys.path:
            sys.path.insert(0, p)

    code = str(req["code"])
    fn_name = str(req["function"])
    expected = list(req.get("params") or [])
    kwargs = decode_value(req.get("kwargs") or {})

    try:
        if restricted:
            check_source(code, policy)
    except SyntaxError as exc:
        return {
            "status": "error",
            "error_type": "SyntaxError",
            "message": f"generated code failed to parse: {exc}",
        }
    except SandboxDenied as exc:
        return {"status": "violation", "message": str(exc)}

    if restricted:
        namespace = _restricted_namespace(policy)
    else:
        namespace = {"__name__": "splice_generated", "__builtins__": builtins}

    import __future__

    try:
        compiled = compile(
            code,
            "<splice-generated>",
            "exec",
            flags=__future__.annotations.compiler_flag,
            dont_inherit=True,
        )
    except SyntaxError as exc:
        return {
            "status": "error",
            "error_type": "SyntaxError",
            "message": f"generated code failed to parse: {exc}",
        }

    if not allow_proc:
        deny_new_processes()

    roots = _read_roots(req.get("sys_path") or [])
    _prune_sys_path(roots)
    denials: list[str] = []
    sys.addaudithook(make_audit_hook(policy, workdir, roots, denials))

    max_chars = int(req.get("max_output_chars") or 65536)
    out, err = _CappedText(max_chars), _CappedText(max_chars)
    sys.stdout, sys.stderr = out, err
    status: dict[str, Any]
    try:
        exec(compiled, namespace, namespace)
        fn = namespace.get(fn_name)
        if not callable(fn):
            raise LookupError(f"function '{fn_name}' not found in generated code")
        params = list(
            fn.__code__.co_varnames[: fn.__code__.co_argcount + fn.__code__.co_kwonlyargcount]
        )
        if params[: len(expected)] != expected:
            raise TypeError(
                f"generated function parameters {params} do not match contract {expected}"
            )
        value = fn(**kwargs)
        status = {"status": "ok", "value": encode_value(value)}
    except SandboxDenied as exc:
        status = {"status": "violation", "message": str(exc)}
    except MemoryError:
        status = {"status": "resource", "message": "memory limit exceeded"}
    except BlockingIOError as exc:
        if not allow_proc and exc.errno == errno.EAGAIN:
            # fork()/clone() refused by RLIMIT_NPROC
            status = {
                "status": "violation",
                "message": "splice sandbox: process creation denied (process limit)",
            }
        else:
            status = {"status": "error", "error_type": type(exc).__name__, "message": str(exc)}
    except RecursionError as exc:
        status = {"status": "error", "error_type": "RecursionError", "message": str(exc)}
    except BaseException as exc:
        status = {"status": "error", "error_type": type(exc).__name__, "message": str(exc)}
    finally:
        sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__

    if denials and status["status"] != "violation":
        # The code caught the denial and carried on; still report it.
        status = {"status": "violation", "message": f"splice sandbox: {denials[0]}"}
    status["stdout"] = out.getvalue()
    status["stderr"] = err.getvalue()
    return status


def main() -> None:
    raw = sys.stdin.buffer.read()
    try:
        fd = os.open(os.devnull, os.O_RDONLY)
        os.dup2(fd, 0)
        os.close(fd)
    except OSError:
        pass
    sys.stdin = io.StringIO("")
    nonce = "splice"
    try:
        req = json.loads(raw)
        nonce = str(req.get("nonce") or nonce)
        result = _run(req, os.getcwd())
    except BaseException as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "message": str(exc)}
    result["protocol"] = PROTOCOL_VERSION
    try:
        line = (nonce + " " + json.dumps(result, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        line = (
            nonce
            + " "
            + json.dumps(
                {"status": "error", "error_type": "SerializationError", "message": str(exc)}
            )
            + "\n"
        ).encode("utf-8")
    view = memoryview(line)
    while view:
        try:
            n = os.write(1, view)
        except OSError:
            break
        view = view[n:]
    # Skip interpreter teardown: atexit handlers and finalizers belong to untrusted code.
    os._exit(0)


if __name__ == "__main__":
    main()
