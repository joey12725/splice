from __future__ import annotations

from pathlib import Path


def find_splice_directory(start_path: Path | None = None) -> Path:
    """Locate the nearest `.splice/` directory by walking up from start_path.

    If none is found, return the conventional location under the current working directory.
    Phase 0: this is a pure resolver; it does not create any directories.
    """

    current: Path = Path(start_path or Path.cwd()).resolve()

    while True:
        candidate = current / ".splice"
        if candidate.is_dir():
            return candidate
        if current == current.parent:
            break
        current = current.parent

    # Fallback to the CWD convention
    return Path.cwd() / ".splice"


