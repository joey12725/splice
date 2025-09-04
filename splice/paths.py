from __future__ import annotations

from pathlib import Path

from .errors import WorkspaceNotFoundError

def find_splice_directory(start_path: Path | None = None) -> Path:
    """Locate the nearest `.splice/` directory by walking up from start_path.

    If none is found, return the conventional location under the current working directory.
    Phase 0: this is a pure resolver; it does not create any directories.
    """

    current: Path = Path(start_path or Path.cwd()).resolve()

    # If caller already passed the `.splice/` directory itself, use it as-is.
    if current.is_dir() and current.name == ".splice":
        return current

    while True:
        candidate = current / ".splice"
        if candidate.is_dir():
            return candidate
        if current == current.parent:
            break
        current = current.parent

    # Fallback to the CWD convention
    return Path.cwd() / ".splice"



def require_splice_directory(start_path: Path | None = None) -> Path:
    """Locate `.splice/` by walking up from start_path; error if not found.

    Raises WorkspaceNotFoundError with guidance to run `splice init`.
    """

    current: Path = Path(start_path or Path.cwd()).resolve()
    while True:
        candidate = current / ".splice"
        if candidate.is_dir():
            return candidate
        if current == current.parent:
            break
        current = current.parent
    raise WorkspaceNotFoundError(
        f"No .splice/ directory found from {current}. Run 'splice init' in your project root."
    )

