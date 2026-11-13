"""Container backends (Docker and Podman).

Each call runs in a throwaway container with no network, a read-only root
filesystem, all capabilities dropped, ``no-new-privileges``, an unprivileged
user, cgroup memory/CPU/PID limits and a small tmpfs as the working directory.
The same runner and audit-hook policy run inside, so behaviour matches the
local backends; the container adds a separate kernel namespace and cgroup.

The image only needs a Python 3.10+ interpreter. Third-party modules in
``sandbox.allow_imports`` must be installed in the image.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from dataclasses import replace
from typing import ClassVar

from .base import ExecutionRequest, ExecutionResult, SandboxPolicy
from .process import _BASE_ENV, ProcessSandbox, runner_source

DEFAULT_IMAGE = "python:3.12-slim"
CONTAINER_WORKDIR = "/sandbox"


class ContainerSandbox(ProcessSandbox):
    """Run each call in a locked-down Docker container."""

    name: ClassVar[str] = "docker"
    isolation: ClassVar[str] = (
        "throwaway container: no network, read-only rootfs, no capabilities, cgroup limits"
    )
    runtime: ClassVar[str] = "docker"
    watch_memory: ClassVar[bool] = False
    startup_grace: ClassVar[float] = 20.0

    def __init__(self, image: str | None = None, python: str = "python3") -> None:
        super().__init__(python=python)
        self.image = image or DEFAULT_IMAGE

    @classmethod
    def is_available(cls) -> bool:
        exe = shutil.which(cls.runtime)
        if not exe:
            return False
        try:
            probe = subprocess.run([exe, "info"], capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return probe.returncode == 0

    def build_command(self, policy: SandboxPolicy, name: str) -> list[str]:
        limits = policy.limits
        mem = f"{max(int(limits.memory_mb), 16)}m"
        fsize = max(int(limits.max_file_size_mb), 1) * 1024 * 1024
        env = dict(_BASE_ENV)
        env.update({"HOME": CONTAINER_WORKDIR, "TMPDIR": CONTAINER_WORKDIR})
        env.update({str(k): str(v) for k, v in policy.env.items()})
        cmd = [
            shutil.which(self.runtime) or self.runtime,
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--network",
            "bridge" if policy.allow_net else "none",
            "--read-only",
            "--tmpfs",
            f"{CONTAINER_WORKDIR}:rw,noexec,nosuid,size={max(limits.max_file_size_mb, 1) * 4}m,"
            "mode=1777",
            "--workdir",
            CONTAINER_WORKDIR,
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            mem,
            "--memory-swap",
            mem,
            "--cpus",
            "1",
            "--pids-limit",
            "64" if policy.allow_subprocess else "16",
            "--ulimit",
            f"fsize={fsize}:{fsize}",
            "--ulimit",
            f"nofile={limits.max_open_files}:{limits.max_open_files}",
            "--ulimit",
            f"cpu={limits.cpu_seconds}:{limits.cpu_seconds + 1}",
        ]
        for key, value in env.items():
            cmd += ["--env", f"{key}={value}"]
        cmd += [self.image, self.python or "python3", "-I", "-B", "-c", runner_source()]
        return cmd

    def execute(self, request: ExecutionRequest, policy: SandboxPolicy) -> ExecutionResult:
        # Host-side extra import paths do not exist inside the image.
        policy = replace(policy, extra_sys_paths=())
        # Container start-up is slower than spawning a local interpreter, so the
        # parent's wall-clock deadline gets a fixed grace period. CPU time is
        # still capped by the ulimit inside the container.
        padded = replace(
            policy,
            limits=replace(
                policy.limits, timeout_seconds=policy.limits.timeout_seconds + self.startup_grace
            ),
        )
        name = f"splice-{secrets.token_hex(6)}"
        cwd = os.getcwd()
        return self.run_child(
            self.build_command(policy, name),
            request,
            padded,
            workdir=cwd,
            env=dict(os.environ),
            cwd=cwd,
        )

    def kill(self, proc: subprocess.Popen[bytes]) -> None:
        args = list(proc.args) if isinstance(proc.args, (list, tuple)) else []
        if proc.poll() is None and "--name" in args:
            name = str(args[args.index("--name") + 1])
            subprocess.run(
                [shutil.which(self.runtime) or self.runtime, "kill", name],
                capture_output=True,
                timeout=15,
                check=False,
            )
        super().kill(proc)


class PodmanSandbox(ContainerSandbox):
    """Same as :class:`ContainerSandbox`, using rootless Podman."""

    name: ClassVar[str] = "podman"
    runtime: ClassVar[str] = "podman"
