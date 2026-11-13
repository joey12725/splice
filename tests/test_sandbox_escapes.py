"""Escape attempts against every available sandbox backend.

Each attack runs twice where it makes sense:

* with the default policy, where the language guard (import allowlist,
  curated builtins, no dunder access) usually stops it first, and
* with ``restricted_python=False``, which simulates an attacker who has
  already beaten the language guard. The process layer (fresh interpreter,
  scrubbed env, rlimits, audit hook) and the OS layer must still hold.

``TestKernelLayer`` goes one step further and runs raw Python under the OS
wrapper with no runner at all: no audit hook, no rlimits. Only the kernel
sandbox stands between the code and the host.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from splice.errors import (
    ExecutionError,
    ExecutionTimeout,
    ResourceLimitExceeded,
    SandboxViolation,
    SerializationError,
)
from splice.sandbox import ExecutionRequest, ProcessSandbox, ResourceLimits, Sandbox, SandboxPolicy
from splice.sandbox.process import build_env, resolve_python

SECRET = "sk-test-0000-do-not-leak"


def run(
    sandbox: Sandbox,
    code: str,
    *,
    restricted: bool = True,
    limits: ResourceLimits | None = None,
    params: tuple[str, ...] = (),
    kwargs: dict[str, Any] | None = None,
    **policy: Any,
) -> Any:
    request = ExecutionRequest(
        code=textwrap.dedent(code),
        function_name="f",
        expected_params=params,
        kwargs=kwargs or {},
    )
    pol = SandboxPolicy(
        restricted_python=restricted,
        limits=limits or ResourceLimits(timeout_seconds=10),
        **policy,
    )
    return sandbox.execute(request, pol).value


@pytest.fixture
def secret_file() -> Iterator[Path]:
    """A file outside the sandbox standing in for ~/.ssh/id_ed25519."""

    with tempfile.TemporaryDirectory(prefix="splice-host-") as d:
        path = Path(d) / ".ssh" / "id_ed25519"
        path.parent.mkdir()
        path.write_text(SECRET)
        yield path


@pytest.fixture
def listener() -> Iterator[int]:
    """A local TCP server that would accept the connection if the sandbox let it."""

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    stop = threading.Event()

    def accept_loop() -> None:
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.close()
            except OSError:
                continue

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    yield srv.getsockname()[1]
    stop.set()
    thread.join(timeout=2)
    srv.close()


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_runs_generated_function(backend: Sandbox) -> None:
    code = """
    import math
    def f(a, b):
        print("computing")
        return math.hypot(a, b)
    """
    assert run(backend, code, params=("a", "b"), kwargs={"a": 3, "b": 4}) == 5.0


def test_rich_values_round_trip(backend: Sandbox) -> None:
    code = """
    def f(x):
        return {"echo": x, "set": {1, 2}, "tuple": (1, "a"), "bytes": b"\\x00\\xff", 1: None}
    """
    value = run(backend, code, params=("x",), kwargs={"x": [1.5, complex(1, 2), {"k": (1,)}]})
    assert value == {
        "echo": [1.5, complex(1, 2), {"k": (1,)}],
        "set": {1, 2},
        "tuple": (1, "a"),
        "bytes": b"\x00\xff",
        1: None,
    }


# --------------------------------------------------------------------------- #
# Filesystem: reading secrets from the host
# --------------------------------------------------------------------------- #


def test_read_ssh_key_blocked_by_language_guard(backend: Sandbox, secret_file: Path) -> None:
    code = """
    def f(path):
        return open(path).read()
    """
    with pytest.raises((SandboxViolation, ExecutionError)) as info:
        run(backend, code, params=("path",), kwargs={"path": str(secret_file)})
    assert SECRET not in str(info.value)


def test_read_ssh_key_blocked_without_language_guard(backend: Sandbox, secret_file: Path) -> None:
    code = """
    def f(path):
        with open(path) as fh:
            return fh.read()
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False, params=("path",), kwargs={"path": str(secret_file)})


def test_real_home_directory_is_not_readable(backend: Sandbox) -> None:
    code = """
    import os
    def f(home):
        return sorted(os.listdir(os.path.join(home, ".ssh")))
    """
    home = os.path.expanduser("~")
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False, params=("home",), kwargs={"home": home})


def test_swallowed_denial_is_still_reported(backend: Sandbox, secret_file: Path) -> None:
    code = """
    def f(path):
        try:
            return open(path).read()
        except BaseException:
            return "nothing to see here"
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False, params=("path",), kwargs={"path": str(secret_file)})


def test_writes_outside_scratch_dir_blocked(backend: Sandbox, tmp_path: Path) -> None:
    target = tmp_path / "pwned.txt"
    code = """
    def f(path):
        with open(path, "w") as fh:
            fh.write("pwned")
        return True
    """
    with pytest.raises(SandboxViolation):
        run(
            backend,
            code,
            restricted=False,
            allow_fs=True,
            params=("path",),
            kwargs={"path": str(target)},
        )
    assert not target.exists()


def test_allow_fs_grants_only_a_private_scratch_dir(backend: Sandbox) -> None:
    code = """
    def f():
        with open("scratch.txt", "w") as fh:
            fh.write("hello")
        with open("scratch.txt") as fh:
            return fh.read()
    """
    assert run(backend, code, allow_fs=True) == "hello"


def test_file_size_limit(backend: Sandbox) -> None:
    code = """
    def f():
        with open("big.bin", "wb") as fh:
            fh.write(b"x" * (4 * 1024 * 1024))
        return True
    """
    limits = ResourceLimits(timeout_seconds=10, max_file_size_mb=1)
    with pytest.raises((ExecutionError, ResourceLimitExceeded)):
        run(backend, code, allow_fs=True, limits=limits)


# --------------------------------------------------------------------------- #
# Environment: API keys and tokens from the parent
# --------------------------------------------------------------------------- #


def test_parent_env_secrets_are_not_inherited(
    backend: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    code = """
    import os
    def f():
        return dict(os.environ)
    """
    env = run(backend, code, restricted=False)
    assert "OPENROUTER_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert SECRET not in repr(env)
    assert os.path.expanduser("~") not in env.get("HOME", "")


def test_env_passthrough_is_explicit(backend: Sandbox) -> None:
    code = """
    import os
    def f():
        return os.environ.get("SPLICE_VISIBLE")
    """
    assert run(backend, code, restricted=False, env={"SPLICE_VISIBLE": "yes"}) == "yes"


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #


def test_network_blocked_by_language_guard(backend: Sandbox, listener: int) -> None:
    code = """
    import socket
    def f(port):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        return "connected"
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, params=("port",), kwargs={"port": listener})


def test_network_blocked_without_language_guard(backend: Sandbox, listener: int) -> None:
    code = """
    import socket
    def f(port):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        return "connected"
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False, params=("port",), kwargs={"port": listener})


def test_dns_lookup_blocked(backend: Sandbox) -> None:
    code = """
    import socket
    def f():
        return socket.gethostbyname("example.com")
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False)


# --------------------------------------------------------------------------- #
# Processes: shells, fork bombs
# --------------------------------------------------------------------------- #


def test_shell_out_blocked(backend: Sandbox, secret_file: Path) -> None:
    code = """
    import subprocess
    def f(path):
        return subprocess.run(["cat", path], capture_output=True, text=True).stdout
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False, params=("path",), kwargs={"path": str(secret_file)})


def test_os_system_blocked(backend: Sandbox, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    code = f"""
    import os
    def f():
        return os.system("touch {marker}")
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False)
    assert not marker.exists()


def test_fork_bomb_contained(backend: Sandbox) -> None:
    code = """
    import os
    def f():
        while True:
            os.fork()
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False, limits=ResourceLimits(timeout_seconds=10))


def test_multiprocessing_blocked(backend: Sandbox) -> None:
    code = """
    import multiprocessing
    def f():
        p = multiprocessing.Process(target=print)
        p.start()
        p.join()
        return "spawned"
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False)


# --------------------------------------------------------------------------- #
# Resource exhaustion
# --------------------------------------------------------------------------- #


def test_infinite_loop_hits_wall_clock(backend: Sandbox) -> None:
    code = """
    def f():
        while True:
            pass
    """
    limits = ResourceLimits(timeout_seconds=1, cpu_seconds=30)
    with pytest.raises(ExecutionTimeout):
        run(backend, code, limits=limits)


def test_busy_loop_hits_cpu_limit(backend: Sandbox) -> None:
    code = """
    def f():
        n = 0
        while True:
            n += 1
    """
    limits = ResourceLimits(timeout_seconds=30, cpu_seconds=1)
    with pytest.raises(ResourceLimitExceeded):
        run(backend, code, limits=limits)


def test_sleep_loop_hits_wall_clock(backend: Sandbox) -> None:
    code = """
    import time
    def f():
        time.sleep(60)
    """
    with pytest.raises(ExecutionTimeout):
        run(backend, code, restricted=False, limits=ResourceLimits(timeout_seconds=1))


def test_huge_allocation_is_stopped(backend: Sandbox) -> None:
    code = """
    def f():
        blob = bytearray(3 * 1024 * 1024 * 1024)
        return len(blob)
    """
    limits = ResourceLimits(timeout_seconds=20, memory_mb=256)
    with pytest.raises(ResourceLimitExceeded):
        run(backend, code, limits=limits)


def test_gradual_memory_growth_is_stopped(backend: Sandbox) -> None:
    code = """
    def f():
        chunks = []
        while True:
            chunks.append(bytearray(16 * 1024 * 1024))
    """
    limits = ResourceLimits(timeout_seconds=20, memory_mb=256)
    with pytest.raises(ResourceLimitExceeded):
        run(backend, code, limits=limits)


def test_output_flood_is_capped(backend: Sandbox) -> None:
    code = """
    def f():
        return "x" * (8 * 1024 * 1024)
    """
    limits = ResourceLimits(timeout_seconds=10, max_output_kb=256)
    with pytest.raises(ResourceLimitExceeded):
        run(backend, code, limits=limits)


def test_print_flood_does_not_corrupt_result(backend: Sandbox) -> None:
    code = """
    def f():
        for _ in range(10000):
            print("noise " * 20)
        return 42
    """
    assert run(backend, code) == 42


# --------------------------------------------------------------------------- #
# Language-level escapes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "code",
    [
        # Classic subclass walk to os._wrap_close
        "def f():\n    return ().__class__.__base__.__subclasses__()\n",
        # Module attribute pivot: statistics imports sys
        "import statistics\ndef f():\n    return statistics.sys.modules['os'].getcwd()\n",
        "import math\ndef f():\n    return math.__loader__\n",
        # Builtins that hand out the keys to the kingdom
        "def f():\n    return __import__('os').getcwd()\n",
        "def f():\n    return eval('1+1')\n",
        "def f():\n    return getattr((), '__class__')\n",
        "def f():\n    return globals()\n",
        # Frame walking
        "def f():\n    g = (x for x in [1])\n    return g.gi_frame.f_back\n",
        "def f():\n    try:\n        1/0\n    except Exception as e:\n"
        "        return e.__traceback__\n",
        # Function internals
        "def f():\n    return f.__globals__\n",
        # Disallowed modules
        "import os\ndef f():\n    return 1\n",
        "from subprocess import run\ndef f():\n    return 1\n",
        "import ctypes\ndef f():\n    return 1\n",
    ],
)
def test_language_guard_blocks_known_escapes(backend: Sandbox, code: str) -> None:
    with pytest.raises(SandboxViolation):
        run(backend, code)


def test_tampering_with_the_audit_hook_is_denied(backend: Sandbox) -> None:
    code = """
    import sys
    def f():
        sys.addaudithook(lambda *args: None)
        return "replaced"
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False)


def test_gc_walk_is_denied(backend: Sandbox) -> None:
    code = """
    import gc
    def f():
        return len(gc.get_objects())
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False)


def test_ctypes_is_denied(backend: Sandbox) -> None:
    code = """
    import ctypes
    def f():
        return ctypes.CDLL(None).getpid()
    """
    with pytest.raises(SandboxViolation):
        run(backend, code, restricted=False)


def test_result_cannot_smuggle_code_into_parent(backend: Sandbox, tmp_path: Path) -> None:
    marker = tmp_path / "parent-pwned"
    code = f"""
    import os
    class Payload:
        def __reduce__(self):
            return (os.system, ("touch {marker}",))
    def f():
        return Payload()
    """
    with pytest.raises(SerializationError):
        run(backend, code, restricted=False)
    assert not marker.exists()


# --------------------------------------------------------------------------- #
# Kernel layer only: no runner, no audit hook, no rlimits
# --------------------------------------------------------------------------- #


def _raw(sandbox: ProcessSandbox, script: str, **policy: Any) -> subprocess.CompletedProcess[str]:
    python = resolve_python(None)
    pol = SandboxPolicy(**policy)
    with tempfile.TemporaryDirectory(prefix="splice-raw-") as d:
        workdir = os.path.realpath(d)
        cmd = sandbox.wrap_command(
            [python, "-I", "-B", "-c", textwrap.dedent(script)],
            workdir=workdir,
            policy=pol,
            python=python,
        )
        return subprocess.run(
            cmd,
            cwd=workdir,
            env=build_env(pol, workdir),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


class TestKernelLayer:
    def test_interpreter_starts(self, os_backend: ProcessSandbox) -> None:
        proc = _raw(os_backend, "import math, json; print(json.dumps(math.pi))")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip().startswith("3.14")

    def test_host_file_unreadable(self, os_backend: ProcessSandbox, secret_file: Path) -> None:
        proc = _raw(os_backend, f"print(open({str(secret_file)!r}).read())")
        assert proc.returncode != 0
        assert SECRET not in proc.stdout

    def test_home_directory_unreadable(self, os_backend: ProcessSandbox) -> None:
        home = os.path.expanduser("~")
        proc = _raw(os_backend, f"import os; print(os.listdir({home!r}))")
        assert proc.returncode != 0

    def test_network_unreachable(self, os_backend: ProcessSandbox, listener: int) -> None:
        proc = _raw(
            os_backend,
            f"import socket; socket.create_connection(('127.0.0.1', {listener}), timeout=2)",
        )
        assert proc.returncode != 0

    def test_cannot_write_outside_workdir(self, os_backend: ProcessSandbox, tmp_path: Path) -> None:
        target = tmp_path / "kernel-pwned"
        proc = _raw(os_backend, f"open({str(target)!r}, 'w').write('x')", allow_fs=True)
        assert proc.returncode != 0
        assert not target.exists()

    @pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt denies fork outright")
    def test_cannot_fork(self, os_backend: ProcessSandbox) -> None:
        proc = _raw(os_backend, "import os; os.fork()")
        assert proc.returncode != 0
