"""Deterministic prompt assembly."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import SpliceConfig
from .paths import require_splice_directory
from .specs import FunctionSpec


@dataclass(frozen=True)
class PromptBundle:
    """Deterministic prompt text assembled from config, spec, docs and the session prompt."""

    text: str


def load_context_docs(doc_names: Iterable[str], start_path: Path | None) -> list[tuple[str, str]]:
    """Load context doc contents from `.splice/context/`.

    Each entry in `doc_names` may be a filename (ending with .md) or a bare name.
    Returns a list of (name, content) pairs for files that exist; missing files are ignored.
    """

    base = require_splice_directory(start_path)
    ctx_dir = base / "context"
    loaded: list[tuple[str, str]] = []
    for name in doc_names:
        filename = name if name.endswith(".md") else f"{name}.md"
        path = ctx_dir / filename
        if path.exists():
            try:
                content = path.read_text()
            except OSError:
                continue
            loaded.append((filename, content))
    return loaded


_load_context_docs = load_context_docs  # backwards-compatible alias


def bundle_prompt(
    spec: FunctionSpec,
    config: SpliceConfig,
    session_prompt: str | None = None,
    start_path: Path | None = None,
) -> PromptBundle:
    """Assemble the model prompt text deterministically from inputs.

    Precedence rules:
    - System prompt: spec.system_prompt overrides config.model.system_prompt
    - Session prompt: provided `session_prompt` overrides spec.prompt
    """

    system_prompt = spec.system_prompt or config.model.system_prompt
    active_prompt = session_prompt if session_prompt is not None else spec.prompt

    # Contracts section
    signature = spec.contracts.signature
    inputs_lines = [f"- {name}: {type_str}" for name, type_str in spec.contracts.inputs.items()]
    output_line = spec.contracts.output

    # Context docs
    context_pairs = load_context_docs(spec.context_docs, start_path)

    # Examples
    examples_section: list[str] = []
    for idx, ex in enumerate(spec.examples, start=1):
        ex_prompt = str(ex.get("prompt", "")).strip()
        ex_func = str(ex.get("function", "")).strip()
        if not ex_prompt and not ex_func:
            continue
        examples_section.append(
            "\n".join(
                [
                    f"Example {idx} — Prompt:",
                    ex_prompt,
                    "",
                    f"Example {idx} — Function:",
                    "```python",
                    ex_func,
                    "```",
                ]
            )
        )

    parts: list[str] = []

    # System prompt first
    parts.extend(["SYSTEM PROMPT:", system_prompt, ""])

    # Contracts for clarity
    parts.extend(
        [
            "CONTRACT SIGNATURE:",
            "```python",
            signature,
            "```",
            "",
            "CONTRACT TYPES:",
            "Inputs:",
            *inputs_lines,
            "Output:",
            f"- {output_line}",
            "",
        ]
    )

    # Context docs if any
    if context_pairs:
        parts.append("CONTEXT DOCS:")
        for filename, content in context_pairs:
            parts.extend([f"# {filename}", content.strip(), ""])  # keep doc titles simple

    # Session-scoped prompt (active)
    parts.extend(["TASK PROMPT:", active_prompt, ""])

    # Examples, if any
    if examples_section:
        parts.append("EXAMPLES:")
        parts.append("\n\n".join(examples_section))
        parts.append("")

    # Final strict instruction (belt-and-suspenders)
    parts.extend(
        [
            "FINAL INSTRUCTION:",
            "Return exactly one valid Python function that matches the contract. No prose.",
        ]
    )

    text = "\n".join(parts).rstrip() + "\n"
    return PromptBundle(text=text)
