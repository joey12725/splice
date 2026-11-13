"""Linux backend: the process sandbox inside bubblewrap namespaces.

``bwrap`` builds a fresh mount namespace that contains only the system
libraries, the interpreter's install and the private working directory, all
read-only except the working directory (and that only with ``allow_fs``).
User, PID, IPC, UTS, cgroup and (by default) network namespaces are unshared,
so the code cannot see the host's processes, home directory or network.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import sys
from typing import ClassVar

from .base import SandboxPolicy
from .process import ProcessSandbox, build_env, python_read_roots

_SYSTEM_RO = (
    "/usr",
    "/lib",
    "/lib64",
    "/lib32",
    "/bin",
    "/sbin",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/alternatives",
    "/usr/share/zoneinfo",
)
_NET_RO = (
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/etc/ssl",
    "/etc/ca-certificates",
)


@functools.lru_cache(maxsize=1)
def _bwrap_works() -> bool:
    exe = shutil.which("bwrap")
    if not exe:
        return False
    try:
        probe = subprocess.run(
            [
                exe,
                "--unshare-all",
                "--die-with-parent",
                "--ro-bind",
                "/usr",
                "/usr",
                "--ro-bind-try",
                "/lib",
                "/lib",
                "--ro-bind-try",
                "/lib64",
                "/lib64",
                "--ro-bind-try",
                "/bin",
                "/bin",
                "/usr/bin/true",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


def build_bwrap_args(*, policy: SandboxPolicy, workdir: str, python: str) -> list[str]:
    exe = shutil.which("bwrap") or "bwrap"
    args = [
        exe,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    if policy.allow_net:
        args.append("--share-net")
        for path in _NET_RO:
            args += ["--ro-bind-try", path, path]
    for path in _SYSTEM_RO:
        args += ["--ro-bind-try", path, path]
    for path in python_read_roots(python, policy.extra_sys_paths):
        args += ["--ro-bind-try", path, path]
    args += ["--bind" if policy.allow_fs else "--ro-bind", workdir, workdir]
    args += ["--chdir", workdir, "--clearenv"]
    return args


class BubblewrapSandbox(ProcessSandbox):
    """Process sandbox + Linux namespaces via bubblewrap."""

    name: ClassVar[str] = "bubblewrap"
    isolation: ClassVar[str] = (
        "process sandbox + private mount/pid/net/user namespaces (host filesystem invisible)"
    )
    # bwrap forks the interpreter, so the watched pid is bwrap itself; RLIMIT_AS
    # inside the namespace enforces memory instead.
    watch_memory: ClassVar[bool] = False

    @classmethod
    def is_available(cls) -> bool:
        return sys.platform.startswith("linux") and _bwrap_works()

    def wrap_command(
        self, command: list[str], *, workdir: str, policy: SandboxPolicy, python: str
    ) -> list[str]:
        env_args: list[str] = []
        for key, value in build_env(policy, workdir).items():
            env_args += ["--setenv", key, value]
        return [
            *build_bwrap_args(policy=policy, workdir=workdir, python=python),
            *env_args,
            *command,
        ]
