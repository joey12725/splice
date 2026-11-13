"""Generate Markdown context docs for Python classes (``.splice/context/<Name>.md``)."""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import find_splice_directory


def _import_from_string(path: str) -> Any:
    module_name, _, attr = path.rpartition(".")
    if not module_name:
        return importlib.import_module(path)
    return getattr(importlib.import_module(module_name), attr)


def _introspect_class(cls: type) -> str:
    lines: list[str] = []
    lines.append(f"# {cls.__name__}")
    doc = (inspect.getdoc(cls) or "").strip()
    if doc:
        lines.append(doc)
        lines.append("")
    lines.append("## Attributes and Methods")
    for name, member in inspect.getmembers(cls):
        if name.startswith("__") and name.endswith("__"):
            continue
        if inspect.isroutine(member):
            sig = ""
            try:
                sig = str(inspect.signature(member))
            except Exception:
                pass
            lines.append(f"- method `{name}{sig}`")
        else:
            lines.append(f"- attr `{name}`")
    return "\n".join(lines).strip() + "\n"


@dataclass
class DocSource:
    name: str
    import_path: str
    doc_strategy: str  # 'class' or 'instance'


def generate_docs(sources: list[DocSource], *, start_path: Path | None = None) -> list[Path]:
    """Write ``.splice/context/<Name>.md`` for each source and return the paths.

    ``doc_strategy: class`` introspects the class (or the object's type) into a
    short Markdown summary. Existing files are left untouched, so hand-edited
    docs survive re-runs.
    """

    base = find_splice_directory(start_path)
    ctx_dir = base / "context"
    ctx_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    for src in sources:
        out_path = ctx_dir / f"{src.name}.md"
        if out_path.exists():
            written.append(out_path)
            continue
        try:
            obj = _import_from_string(src.import_path)
            if src.doc_strategy == "class":
                if inspect.isclass(obj):
                    content = _introspect_class(obj)
                else:
                    # Try to use the object's type for class-like docs
                    content = _introspect_class(type(obj))
            else:
                # Minimal placeholder for unsupported strategies
                content = f"# {src.name}\nDocumentation placeholder.\n"
        except Exception:
            content = f"# {src.name}\nDocumentation unavailable (import failed).\n"

        out_path.write_text(content)
        written.append(out_path)

    return written
