"""macOS backend: the process sandbox wrapped in a deny-by-default Seatbelt profile.

``sandbox-exec`` applies a kernel-enforced profile before Python starts. The
profile denies everything, then allows only what the interpreter needs to boot:
reads of its own install and system libraries, the private working directory,
``/dev/null`` and ``/dev/urandom``. Network, process creation (fork/exec of
anything but the interpreter) and writes outside the working directory are
refused by the kernel, independent of anything Python does.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import ClassVar

from .base import SandboxPolicy
from .process import ProcessSandbox, python_read_roots

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_SYSTEM_READ_ROOTS = (
    "/usr/lib",
    "/usr/share/zoneinfo",
    "/System",
    "/private/var/db/dyld",
    "/private/var/db/timezone",
    "/Library/Apple",
)


def _quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_profile(*, policy: SandboxPolicy, workdir: str, python: str) -> str:
    """Render the Seatbelt (SBPL) profile for one execution."""

    read_roots = python_read_roots(python, policy.extra_sys_paths)
    executables = {python, os.path.realpath(python)}
    lines = [
        "(version 1)",
        "(deny default)",
        # Framework builds re-exec into Python.app, so the install tree is executable.
        # Anything exec'd inherits this same profile.
        "(allow process-exec "
        + " ".join(f"(literal {_quote(p)})" for p in sorted(executables))
        + " "
        + " ".join(f"(subpath {_quote(p)})" for p in read_roots)
        + ")",
        # stat() anywhere; contents are still denied. Needed for path resolution.
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/urandom")'
        ' (literal "/dev/random") (literal "/dev/zero"))',
        "(allow file-read* "
        + " ".join(f"(subpath {_quote(p)})" for p in (*_SYSTEM_READ_ROOTS, *read_roots))
        + ")",
        '(allow file-write-data (literal "/dev/null"))',
        "(allow sysctl-read)",
        "(allow signal (target self))",
    ]
    if policy.allow_fs:
        lines.append(f"(allow file-read* file-write* (subpath {_quote(workdir)}))")
    else:
        lines.append(f"(allow file-read* (subpath {_quote(workdir)}))")
    if policy.allow_net:
        lines += [
            "(allow network*)",
            "(allow system-socket)",
            '(allow mach-lookup (global-name "com.apple.dnssd.service")'
            ' (global-name "com.apple.SystemConfiguration.configd"))',
            '(allow file-read* (subpath "/private/etc") (subpath "/private/var/run"))',
        ]
    if policy.allow_subprocess:
        lines += [
            "(allow process-fork)",
            "(allow process-exec*)",
            '(allow file-read* (subpath "/bin") (subpath "/usr/bin") (subpath "/usr/sbin")'
            ' (subpath "/sbin") (subpath "/usr/libexec"))',
        ]
    return "\n".join(lines) + "\n"


class SeatbeltSandbox(ProcessSandbox):
    """Process sandbox + kernel-enforced Seatbelt profile (macOS)."""

    name: ClassVar[str] = "seatbelt"
    isolation: ClassVar[str] = (
        "process sandbox + kernel deny-by-default profile: no network, no fork/exec, "
        "no reads outside the interpreter"
    )

    @classmethod
    def is_available(cls) -> bool:
        return sys.platform == "darwin" and bool(
            os.path.exists(SANDBOX_EXEC) or shutil.which("sandbox-exec")
        )

    def wrap_command(
        self, command: list[str], *, workdir: str, policy: SandboxPolicy, python: str
    ) -> list[str]:
        profile = build_profile(policy=policy, workdir=workdir, python=python)
        return [SANDBOX_EXEC, "-p", profile, *command]
