"""Dependency policy and per-session virtual environments.

Contracts that reference third-party types (``numpy.ndarray``, a pydantic
model, ...) need those packages importable inside the sandbox. The policy in
``dependencies.policy`` decides what happens when they are missing:

* ``off``: do nothing.
* ``if-present``: require them to be importable already; fail fast otherwise.
* ``allow``: install missing packages into a per-session venv under
  ``.splice/cache/venv/<session>`` and expose its ``site-packages`` to the
  sandbox as a read-only import root.

Installation always runs in the trusted parent, never inside the sandbox.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import venv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import DependenciesError
from .paths import require_splice_directory

POLICIES = ("off", "if-present", "allow")


@dataclass
class DependencyPolicy:
    """Apply a dependency policy to the *current* interpreter."""

    policy: str  # off | if-present | allow

    def ensure(self, modules: Iterable[str]) -> None:
        if self.policy not in POLICIES:
            raise DependenciesError(f"Unknown dependency policy: {self.policy}")
        if self.policy == "off":
            return
        for module in modules:
            if _importable(module, []):
                continue
            if self.policy == "if-present":
                raise DependenciesError(
                    f"Required dependency '{module}' not installed under if-present policy"
                )
            _pip_install(sys.executable, module)


@dataclass
class SessionEnv:
    venv_dir: Path | None
    site_packages: list[Path]
    pip_cache_dir: Path


def _venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _compute_site_packages_dir(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Lib" / "site-packages"
    major, minor = sys.version_info[:2]
    return venv_dir / "lib" / f"python{major}.{minor}" / "site-packages"


def create_session_env(*, start_path: Path | None, session_id: str) -> SessionEnv:
    base = require_splice_directory(start_path)
    venv_dir = base / "cache" / "venv" / session_id
    pip_cache_dir = (base / "cache" / "pip").resolve()
    pip_cache_dir.mkdir(parents=True, exist_ok=True)
    if not venv_dir.exists():
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=True).create(venv_dir)
    return SessionEnv(
        venv_dir=venv_dir,
        site_packages=[_compute_site_packages_dir(venv_dir)],
        pip_cache_dir=pip_cache_dir,
    )


def _importable(module: str, extra_paths: list[Path]) -> bool:
    original = list(sys.path)
    try:
        for p in map(str, extra_paths):
            if p not in sys.path:
                sys.path.insert(0, p)
        importlib.import_module(module)
        return True
    except ImportError:
        return False
    finally:
        sys.path[:] = original


def _pip_install(python: str | Path, module: str, *extra: str) -> None:
    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", module, *extra],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DependenciesError(f"Failed to install dependency '{module}': {exc}") from exc


def prepare_dependencies(
    *,
    policy: str,
    modules: Iterable[str],
    start_path: Path | None,
    session_id: str,
) -> list[str]:
    """Apply ``policy`` to ``modules`` and return extra import roots for the sandbox."""

    modules_list = list(dict.fromkeys(modules))
    if policy not in POLICIES:
        raise DependenciesError(f"Unknown dependency policy: {policy}")
    if policy == "off" or not modules_list:
        return []

    if policy == "if-present":
        for module in modules_list:
            if not _importable(module, []):
                raise DependenciesError(
                    f"Required dependency '{module}' not installed under if-present policy"
                )
        return []

    env = create_session_env(start_path=start_path, session_id=session_id)
    assert env.venv_dir is not None
    env_python = _venv_python_path(env.venv_dir)
    for module in modules_list:
        if not _importable(module, env.site_packages):
            _pip_install(env_python, module, "--cache-dir", str(env.pip_cache_dir))
    return [str(p) for p in env.site_packages if p.exists()]
