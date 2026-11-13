"""Subprocess backend: a fresh, isolated interpreter per call.

Every execution gets:

* a brand-new ``python -I -B`` process (no inherited memory, no user site,
  no ``PYTHON*`` variables) started in its own session/process group;
* a private ``0700`` temporary working directory that is deleted afterwards;
* an environment built from scratch: no API keys or tokens from the parent;
* POSIX rlimits for CPU time, address space (Linux), file size, open files,
  core dumps, and process creation;
* a CPython audit hook that denies filesystem access outside the interpreter's
  own install, network, and process creation unless the policy allows them;
* a wall-clock timeout, an output cap, and (on macOS) a memory watchdog, all
  enforced from the parent by SIGKILLing the whole process group.

Subclasses wrap the command with an OS sandbox (seatbelt, bubblewrap,
containers) to add a kernel-enforced boundary on top.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import IO, Any, ClassVar

from ..errors import (
    ExecutionError,
    ExecutionTimeout,
    ResourceLimitExceeded,
    SandboxViolation,
    SerializationError,
)
from . import _runner
from .base import ExecutionRequest, ExecutionResult, Sandbox, SandboxPolicy

RUNNER_FILENAME = "_splice_runner.py"
_BASE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    # Keep numerical libraries single-threaded and inside the memory budget.
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


def runner_source() -> str:
    """Source of the child bootstrap, shipped into every sandbox."""

    return resources.files("splice.sandbox").joinpath("_runner.py").read_text(encoding="utf-8")


def resolve_python(python: str | None) -> str:
    exe = python or sys.executable
    found = shutil.which(exe) if os.sep not in exe else exe
    if not found:
        raise ExecutionError(f"sandbox interpreter not found: {exe}")
    return found


_PROBE_ROOTS = (
    "import json, site, sys, sysconfig; p = sysconfig.get_paths(); print(json.dumps("
    "[sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]"
    " + site.getsitepackages()"
    " + [p.get(k, '') for k in ('stdlib', 'platstdlib', 'purelib', 'platlib')]))"
)


def python_read_roots(python: str, extra: Sequence[str] = ()) -> list[str]:
    """Directories a sandboxed interpreter must be able to read to start up."""

    roots: list[str] = []
    if os.path.realpath(python) == os.path.realpath(sys.executable):
        import site
        import sysconfig

        candidates = [sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix]
        candidates += [p for p in site.getsitepackages() if p]
        candidates += [
            sysconfig.get_paths().get(k, "") for k in ("stdlib", "platstdlib", "purelib", "platlib")
        ]
    else:
        probe = subprocess.run(
            [python, "-I", "-c", _PROBE_ROOTS],
            capture_output=True,
            text=True,
            timeout=30,
            env=dict(_BASE_ENV),
            check=False,
        )
        candidates = json.loads(probe.stdout or "[]")
    candidates += [os.path.dirname(python), os.path.dirname(os.path.realpath(python))]
    candidates += list(extra)
    for c in candidates:
        if not c:
            continue
        for path in {os.path.abspath(c), os.path.realpath(c)}:
            if os.path.exists(path) and path not in roots and path != os.sep:
                roots.append(path)
    return roots


def build_env(policy: SandboxPolicy, workdir: str) -> dict[str, str]:
    env = dict(_BASE_ENV)
    env.update({"HOME": workdir, "TMPDIR": workdir, "TMP": workdir, "TEMP": workdir})
    env.update({str(k): str(v) for k, v in policy.env.items()})
    return env


def memory_footprint_bytes(pid: int) -> int | None:
    """Current memory footprint of ``pid``, or None if it cannot be measured."""

    if sys.platform == "darwin":
        return _darwin_footprint(pid)
    try:
        with open(f"/proc/{pid}/statm", encoding="ascii") as fh:
            resident_pages = int(fh.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


_libproc: Any = None


def _darwin_footprint(pid: int) -> int | None:
    global _libproc
    import ctypes

    class RUsageInfoV0(ctypes.Structure):
        _fields_ = [
            ("ri_uuid", ctypes.c_uint8 * 16),
            ("ri_user_time", ctypes.c_uint64),
            ("ri_system_time", ctypes.c_uint64),
            ("ri_pkg_idle_wkups", ctypes.c_uint64),
            ("ri_interrupt_wkups", ctypes.c_uint64),
            ("ri_pageins", ctypes.c_uint64),
            ("ri_wired_size", ctypes.c_uint64),
            ("ri_resident_size", ctypes.c_uint64),
            ("ri_phys_footprint", ctypes.c_uint64),
            ("ri_proc_start_abstime", ctypes.c_uint64),
            ("ri_proc_exit_abstime", ctypes.c_uint64),
        ]

    try:
        if _libproc is None:
            _libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        info = RUsageInfoV0()
        if _libproc.proc_pid_rusage(int(pid), 0, ctypes.byref(info)) != 0:
            return None
        return int(info.ri_phys_footprint)
    except OSError:
        return None


class _CappedReader(threading.Thread):
    def __init__(self, stream: IO[bytes], limit: int, on_overflow: threading.Event) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self._overflow = on_overflow
        self.data = bytearray()

    def run(self) -> None:
        while True:
            chunk = self._stream.read(65536)
            if not chunk:
                break
            room = self._limit - len(self.data)
            if room > 0:
                self.data += chunk[:room]
            if len(chunk) > room:
                self._overflow.set()
        self._stream.close()


class ProcessSandbox(Sandbox):
    """Fresh interpreter + rlimits + audit hook + scrubbed env. Works everywhere."""

    name: ClassVar[str] = "process"
    isolation: ClassVar[str] = (
        "fresh interpreter, scrubbed env, private temp dir, rlimits, audit-hook policy"
    )
    watch_memory: ClassVar[bool] = True
    poll_interval: ClassVar[float] = 0.02

    def __init__(self, python: str | None = None) -> None:
        self.python = python

    @classmethod
    def is_available(cls) -> bool:
        return os.name == "posix"

    # Hooks for OS-level wrappers -------------------------------------------------

    def wrap_command(
        self, command: list[str], *, workdir: str, policy: SandboxPolicy, python: str
    ) -> list[str]:
        """Return the command to launch; subclasses prepend their sandbox tool."""

        return command

    def kill(self, proc: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    # Core ------------------------------------------------------------------------

    def interpreter_command(self, python: str, runner_path: str) -> list[str]:
        return [python, "-I", "-B", runner_path]

    def execute(self, request: ExecutionRequest, policy: SandboxPolicy) -> ExecutionResult:
        python = resolve_python(self.python)
        workdir = os.path.realpath(tempfile.mkdtemp(prefix="splice-"))
        try:
            os.chmod(workdir, 0o700)
            runner_path = os.path.join(workdir, RUNNER_FILENAME)
            Path(runner_path).write_text(runner_source(), encoding="utf-8")
            command = self.wrap_command(
                self.interpreter_command(python, runner_path),
                workdir=workdir,
                policy=policy,
                python=python,
            )
            return self.run_child(command, request, policy, workdir=workdir)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def run_child(
        self,
        command: list[str],
        request: ExecutionRequest,
        policy: SandboxPolicy,
        *,
        workdir: str,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecutionResult:
        limits = policy.limits
        nonce = secrets.token_hex(16)
        payload = encode_request(request, policy, nonce)
        output_cap = max(int(limits.max_output_kb), 1) * 1024 * 4 + 65536

        started = time.perf_counter()
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd or workdir,
                env=env if env is not None else build_env(policy, workdir),
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise ExecutionError(f"failed to start sandbox ({self.name}): {exc}") from exc

        overflow = threading.Event()
        assert proc.stdout is not None and proc.stderr is not None and proc.stdin is not None
        out_reader = _CappedReader(proc.stdout, output_cap, overflow)
        err_reader = _CappedReader(proc.stderr, 65536, threading.Event())
        out_reader.start()
        err_reader.start()

        def feed() -> None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(payload)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()

        deadline = started + float(limits.timeout_seconds)
        mem_limit = int(limits.memory_mb) * 1024 * 1024
        killed_for: str | None = None
        interval = 0.002
        while True:
            try:
                proc.wait(timeout=interval)
                break
            except subprocess.TimeoutExpired:
                pass
            interval = min(interval * 2, self.poll_interval)
            if time.perf_counter() > deadline:
                killed_for = "timeout"
            elif overflow.is_set():
                killed_for = "output"
            elif self.watch_memory and mem_limit > 0:
                used = memory_footprint_bytes(proc.pid)
                if used is not None and used > mem_limit:
                    killed_for = "memory"
            if killed_for:
                self.kill(proc)
                proc.wait()
                break
        if killed_for is None and overflow.is_set():
            killed_for = "output"
        # Reap anything left in the group (e.g. if subprocesses were allowed).
        self.kill(proc)
        feeder.join(timeout=1)
        out_reader.join(timeout=5)
        err_reader.join(timeout=5)
        duration_ms = (time.perf_counter() - started) * 1000.0

        return self.interpret(
            nonce=nonce,
            stdout=bytes(out_reader.data),
            stderr=bytes(err_reader.data),
            returncode=proc.returncode,
            killed_for=killed_for,
            policy=policy,
            duration_ms=duration_ms,
        )

    def interpret(
        self,
        *,
        nonce: str,
        stdout: bytes,
        stderr: bytes,
        returncode: int | None,
        killed_for: str | None,
        policy: SandboxPolicy,
        duration_ms: float,
    ) -> ExecutionResult:
        limits = policy.limits
        if killed_for == "timeout":
            raise ExecutionTimeout(
                f"execution exceeded the {limits.timeout_seconds:g}s wall-clock limit"
            )
        if killed_for == "memory":
            raise ResourceLimitExceeded(
                f"execution exceeded the {limits.memory_mb} MB memory limit"
            )
        if killed_for == "output":
            raise ResourceLimitExceeded(
                f"execution exceeded the {limits.max_output_kb} KB output limit"
            )

        response = _find_response(stdout, nonce)
        if response is None:
            raise _exit_error(returncode, stderr, limits.cpu_seconds, limits.memory_mb, self.name)

        status = response.get("status")
        if status == "ok":
            try:
                value = _runner.decode_value(response.get("value"))
            except (ValueError, TypeError, KeyError) as exc:
                raise SerializationError(f"could not decode sandbox result: {exc}") from exc
            return ExecutionResult(
                value=value,
                stdout=str(response.get("stdout", "")),
                stderr=str(response.get("stderr", "")),
                duration_ms=duration_ms,
                backend=self.name,
            )
        message = str(response.get("message", ""))
        if status == "violation":
            raise SandboxViolation(message)
        if status == "resource":
            raise ResourceLimitExceeded(f"{message} ({limits.memory_mb} MB)")
        error_type = str(response.get("error_type", "Error"))
        if error_type == "SerializationError" or "cannot cross the sandbox boundary" in message:
            raise SerializationError(message)
        raise ExecutionError(f"{error_type}: {message}")


def encode_request(request: ExecutionRequest, policy: SandboxPolicy, nonce: str) -> bytes:
    try:
        kwargs = _runner.encode_value(dict(request.kwargs))
    except TypeError as exc:
        raise SerializationError(f"argument cannot be passed into the sandbox: {exc}") from exc
    limits = policy.limits
    body = {
        "nonce": nonce,
        "code": request.code,
        "function": request.function_name,
        "params": list(request.expected_params),
        "kwargs": kwargs,
        "policy": policy.to_wire(),
        "limits": {
            "cpu_seconds": limits.cpu_seconds,
            "memory_mb": limits.memory_mb,
            "max_file_size_mb": limits.max_file_size_mb,
            "max_open_files": limits.max_open_files,
        },
        "sys_path": list(policy.extra_sys_paths),
        "max_output_chars": limits.max_output_kb * 1024,
    }
    return json.dumps(body, allow_nan=False).encode("utf-8")


def _find_response(stdout: bytes, nonce: str) -> dict[str, Any] | None:
    marker = nonce.encode("ascii") + b" "
    for line in reversed(stdout.splitlines()):
        if line.startswith(marker):
            try:
                data = json.loads(line[len(marker) :])
            except ValueError:
                return None
            return data if isinstance(data, dict) else None
    return None


def _exit_error(
    returncode: int | None, stderr: bytes, cpu_seconds: int, memory_mb: int, backend: str
) -> ExecutionError:
    tail = stderr.decode("utf-8", "replace").strip()[-800:]
    sig = 0
    if returncode is not None and returncode < 0:
        sig = -returncode
    elif returncode is not None and 128 < returncode < 128 + 65:
        # Wrappers (bwrap, container runtimes) report a signalled child as 128 + signal.
        sig = returncode - 128
    if sig:
        if sig == getattr(signal, "SIGXCPU", -1):
            return ResourceLimitExceeded(f"execution exceeded the {cpu_seconds}s CPU time limit")
        if sig == signal.SIGKILL:
            return ResourceLimitExceeded(
                f"sandbox process was killed (CPU limit of {cpu_seconds}s or memory limit of "
                f"{memory_mb} MB)"
            )
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = str(sig)
        return ExecutionError(f"sandbox process died with signal {name}. {tail}".strip())
    detail = tail or "no output"
    return ExecutionError(f"sandbox ({backend}) exited with code {returncode}: {detail}")
