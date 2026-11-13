"""Sandboxed execution backends for generated code.

Pick a backend with ``sandbox.backend`` in ``splice.yaml``:

=============  ==============================================================
``auto``       Strongest local backend available (default): ``seatbelt`` on
               macOS, ``bubblewrap`` on Linux when usable, else ``process``.
``process``    Fresh isolated interpreter, scrubbed env, rlimits, audit hook.
``seatbelt``   ``process`` + macOS kernel sandbox profile (deny by default).
``bubblewrap`` ``process`` + Linux namespaces (host filesystem invisible).
``docker``     Throwaway locked-down container per call.
``podman``     Same as ``docker`` with Podman.
=============  ==============================================================

Custom backends subclass :class:`Sandbox` and are registered with
:func:`register_backend`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..errors import ConfigError, SandboxUnavailableError
from .base import ExecutionRequest, ExecutionResult, ResourceLimits, Sandbox, SandboxPolicy
from .bubblewrap import BubblewrapSandbox
from .container import ContainerSandbox, PodmanSandbox
from .process import ProcessSandbox
from .seatbelt import SeatbeltSandbox

if TYPE_CHECKING:
    from ..config import SandboxConfig

__all__ = [
    "BubblewrapSandbox",
    "ContainerSandbox",
    "ExecutionRequest",
    "ExecutionResult",
    "PodmanSandbox",
    "ProcessSandbox",
    "ResourceLimits",
    "Sandbox",
    "SandboxPolicy",
    "SeatbeltSandbox",
    "available_backends",
    "create_sandbox",
    "policy_from_config",
    "register_backend",
    "resolve_backend_name",
]

BackendFactory = Callable[["SandboxConfig"], Sandbox]

_BACKENDS: dict[str, tuple[type[Sandbox], BackendFactory]] = {}
AUTO_ORDER = ("seatbelt", "bubblewrap", "process")


def register_backend(name: str, cls: type[Sandbox], factory: BackendFactory | None = None) -> None:
    """Make a backend selectable as ``sandbox.backend: <name>``."""

    _BACKENDS[name] = (cls, factory or (lambda _cfg: cls()))


register_backend("process", ProcessSandbox, lambda cfg: ProcessSandbox(python=cfg.python))
register_backend("seatbelt", SeatbeltSandbox, lambda cfg: SeatbeltSandbox(python=cfg.python))
register_backend("bubblewrap", BubblewrapSandbox, lambda cfg: BubblewrapSandbox(python=cfg.python))
register_backend("docker", ContainerSandbox, lambda cfg: ContainerSandbox(cfg.container_image))
register_backend("podman", PodmanSandbox, lambda cfg: PodmanSandbox(cfg.container_image))


def available_backends() -> dict[str, bool]:
    """Map of registered backend name to whether it can run on this machine."""

    return {name: cls.is_available() for name, (cls, _) in _BACKENDS.items()}


def resolve_backend_name(name: str) -> str:
    """Resolve ``auto`` to a concrete backend; validate explicit names."""

    if name == "auto":
        for candidate in AUTO_ORDER:
            if _BACKENDS[candidate][0].is_available():
                return candidate
        raise SandboxUnavailableError("no sandbox backend is available on this platform")
    if name not in _BACKENDS:
        raise ConfigError(
            f"unknown sandbox backend {name!r}; choose one of: auto, {', '.join(sorted(_BACKENDS))}"
        )
    if not _BACKENDS[name][0].is_available():
        raise SandboxUnavailableError(f"sandbox backend {name!r} is not available on this machine")
    return name


def create_sandbox(config: SandboxConfig) -> Sandbox:
    """Instantiate the backend selected by ``config.backend``."""

    name = resolve_backend_name(config.backend)
    return _BACKENDS[name][1](config)


def policy_from_config(
    config: SandboxConfig,
    *,
    extra_sys_paths: tuple[str, ...] | list[str] = (),
    timeout_seconds: float | None = None,
) -> SandboxPolicy:
    import os

    limits = ResourceLimits(
        timeout_seconds=float(
            timeout_seconds if timeout_seconds is not None else config.timeout_seconds
        ),
        cpu_seconds=int(config.cpu_seconds),
        memory_mb=int(config.memory_mb),
        max_file_size_mb=int(config.max_file_size_mb),
        max_open_files=int(config.max_open_files),
        max_output_kb=int(config.max_output_kb),
    )
    env = {name: os.environ[name] for name in config.env_passthrough if name in os.environ}
    return SandboxPolicy(
        allow_imports=tuple(config.allow_imports),
        allow_fs=bool(config.allow_fs),
        allow_net=bool(config.allow_net),
        allow_subprocess=bool(config.allow_subprocess),
        restricted_python=bool(config.restricted_python),
        limits=limits,
        env=env,
        extra_sys_paths=tuple(extra_sys_paths),
    )
