from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .errors import DependenciesError
from .paths import find_splice_directory


@dataclass
class DependencyPolicy:
    policy: str  # off | if-present | allow

    def ensure(self, modules: Iterable[str]) -> None:
        if self.policy == "off":
            return
        if self.policy == "if-present":
            # Best-effort: import to check presence, but do not install
            for m in modules:
                try:
                    __import__(m)
                except Exception:
                    raise DependenciesError(f"Required dependency '{m}' not installed under if-present policy")
            return
        if self.policy == "allow":
            # Attempt to install missing modules into current environment
            for m in modules:
                try:
                    __import__(m)
                except Exception:
                    try:
                        subprocess.run([sys.executable, "-m", "pip", "install", m], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    except Exception as exc:  # noqa: BLE001
                        raise DependenciesError(f"Failed to install dependency '{m}': {exc}")
            return
        raise DependenciesError(f"Unknown dependency policy: {self.policy}")


@dataclass
class SessionEnv:
    venv_dir: Optional[Path]
    site_packages: List[Path]
    pip_cache_dir: Path


def _venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _compute_site_packages_dir(venv_dir: Path) -> Path:
    # Heuristic based on current interpreter version
    major = sys.version_info.major
    minor = sys.version_info.minor
    if os.name == "nt":
        return venv_dir / "Lib" / "site-packages"
    return venv_dir / "lib" / f"python{major}.{minor}" / "site-packages"


def create_session_env(*, start_path: Optional[Path], session_id: str) -> SessionEnv:
    base = find_splice_directory(start_path)
    venv_root = base / "cache" / "venv"
    venv_dir = venv_root / session_id
    pip_cache_dir = (base / "cache" / "pip").resolve()
    pip_cache_dir.mkdir(parents=True, exist_ok=True)

    if not venv_dir.exists():
        import venv as _venv

        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        builder = _venv.EnvBuilder(with_pip=True, clear=False, symlinks=True)
        builder.create(venv_dir)

    site_packages = [_compute_site_packages_dir(venv_dir)]
    return SessionEnv(venv_dir=venv_dir, site_packages=site_packages, pip_cache_dir=pip_cache_dir)


def _import_with_extra_paths(module: str, extra_paths: List[Path]) -> bool:
    try:
        if not extra_paths:
            __import__(module)
            return True
        # Temporarily extend sys.path
        original = list(sys.path)
        try:
            for p in map(str, extra_paths):
                if p not in sys.path:
                    sys.path.insert(0, p)
            __import__(module)
            return True
        finally:
            sys.path[:] = original
    except Exception:
        return False


def prepare_dependencies(
    *,
    policy: str,
    modules: Iterable[str],
    start_path: Optional[Path],
    session_id: str,
) -> List[str]:
    """Ensure dependencies according to policy and return extra sys.path entries.

    - off: no action
    - if-present: assert importable in current env; raise if not
    - allow: create per-session venv under .splice/cache/venv/<session>, install missing
             modules using pip with shared cache .splice/cache/pip, and return that venv's
             site-packages paths to prepend during execution.
    """

    modules_list = list(dict.fromkeys(modules))
    if policy == "off" or not modules_list:
        return []

    if policy == "if-present":
        for m in modules_list:
            if not _import_with_extra_paths(m, []):
                raise DependenciesError(f"Required dependency '{m}' not installed under if-present policy")
        return []

    if policy == "allow":
        env = create_session_env(start_path=start_path, session_id=session_id)
        env_python = _venv_python_path(env.venv_dir) if env.venv_dir is not None else None
        for m in modules_list:
            if _import_with_extra_paths(m, env.site_packages):
                continue
            if env_python is None:
                raise DependenciesError("Session venv not available for installation")
            try:
                subprocess.run(
                    [str(env_python), "-m", "pip", "install", m, "--cache-dir", str(env.pip_cache_dir)],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception as exc:  # noqa: BLE001
                raise DependenciesError(f"Failed to install dependency '{m}' into session env: {exc}")
        # Return sys.path strings for caller to pass into Executor
        return [str(p) for p in env.site_packages if p.exists()]

    raise DependenciesError(f"Unknown dependency policy: {policy}")


