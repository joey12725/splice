"""Pluggable sandbox interface.

A :class:`Sandbox` takes an :class:`ExecutionRequest` (generated source plus
call arguments) and a :class:`SandboxPolicy` (what the code may touch and how
much it may consume) and returns an :class:`ExecutionResult`. Generated code is
never executed in the caller's process.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True)
class ResourceLimits:
    """Hard limits applied to every execution."""

    timeout_seconds: float = 10.0
    """Wall-clock budget. The whole process group is SIGKILLed when it runs out."""
    cpu_seconds: int = 10
    """CPU time (RLIMIT_CPU). Busy loops die even if the wall clock is generous."""
    memory_mb: int = 512
    """Address space on Linux (RLIMIT_AS), physical footprint watchdog on macOS,
    cgroup limit for containers."""
    max_file_size_mb: int = 16
    """Largest file the code may write (RLIMIT_FSIZE)."""
    max_open_files: int = 64
    """File descriptor ceiling (RLIMIT_NOFILE)."""
    max_output_kb: int = 1024
    """Cap on captured stdout/stderr and on the encoded result."""


@dataclass(frozen=True)
class SandboxPolicy:
    """What generated code is allowed to do. Everything defaults to off."""

    allow_imports: tuple[str, ...] = ("math", "statistics", "numpy")
    allow_fs: bool = False
    """Read/write access to a private, throwaway working directory. Never the host filesystem."""
    allow_net: bool = False
    allow_subprocess: bool = False
    restricted_python: bool = True
    """Language-level guard: import allowlist, curated builtins, no dunder access.
    Turning it off leaves the process and OS layers in charge."""
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    env: Mapping[str, str] = field(default_factory=dict)
    """Environment variables passed into the sandbox. Nothing is inherited implicitly."""
    extra_sys_paths: tuple[str, ...] = ()
    """Additional read-only import roots (for per-session dependency environments)."""

    def to_wire(self) -> dict[str, Any]:
        return {
            "allow_imports": list(self.allow_imports),
            "allow_fs": self.allow_fs,
            "allow_net": self.allow_net,
            "allow_subprocess": self.allow_subprocess,
            "restricted_python": self.restricted_python,
        }


@dataclass(frozen=True)
class ExecutionRequest:
    code: str
    function_name: str
    expected_params: tuple[str, ...]
    kwargs: Mapping[str, Any]


@dataclass(frozen=True)
class ExecutionResult:
    value: Any
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    backend: str = ""


class Sandbox(abc.ABC):
    """Base class for execution backends.

    Subclasses implement :meth:`execute` and :meth:`is_available`. Register them
    with :func:`splice.sandbox.register_backend` to make them selectable from
    ``splice.yaml``.
    """

    name: ClassVar[str] = "abstract"
    isolation: ClassVar[str] = ""
    """One-line description of the isolation boundary, shown by ``splice sandbox``."""

    @classmethod
    def is_available(cls) -> bool:
        return True

    @abc.abstractmethod
    def execute(self, request: ExecutionRequest, policy: SandboxPolicy) -> ExecutionResult:
        """Run ``request`` under ``policy``.

        Raises :class:`splice.errors.SandboxViolation` for policy denials,
        :class:`splice.errors.ResourceLimitExceeded` (or its subclass
        :class:`splice.errors.ExecutionTimeout`) when a limit trips, and
        :class:`splice.errors.ExecutionError` for anything else.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} backend={self.name!r}>"
