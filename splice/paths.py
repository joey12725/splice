"""Locate the project's ``.splice/`` workspace directory."""

from __future__ import annotations

from pathlib import Path

from .errors import WorkspaceNotFoundError


def _walk_up(start_path: Path | None) -> tuple[Path, Path | None]:
    start = Path(start_path or Path.cwd()).resolve()
    if start.name == ".splice" and start.is_dir():
        return start, start
    current = start
    while True:
        candidate = current / ".splice"
        if candidate.is_dir():
            return start, candidate
        if current == current.parent:
            return start, None
        current = current.parent


def find_splice_directory(start_path: Path | None = None) -> Path:
    """Return the nearest existing ``.splice/`` at or above ``start_path``.

    If there is none, return ``<start_path>/.splice`` (the place ``splice init``
    would create it). This function never creates directories.
    """

    start, found = _walk_up(start_path)
    return found if found is not None else start / ".splice"


def require_splice_directory(start_path: Path | None = None) -> Path:
    """Like :func:`find_splice_directory` but raise if no workspace exists."""

    start, found = _walk_up(start_path)
    if found is None:
        raise WorkspaceNotFoundError(
            f"No .splice/ directory found at or above {start}. "
            "Run 'splice init' in your project root."
        )
    return found
