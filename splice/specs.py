from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .errors import SpecError, SpecNotFoundError
from .paths import require_splice_directory


@dataclass
class Contracts:
    signature: str
    inputs: dict[str, str]
    output: str
    pydantic: dict[str, str] = field(default_factory=dict)


@dataclass
class FunctionSpec:
    name: str
    version: str
    description: str
    prompt: str
    system_prompt: str | None
    contracts: Contracts
    context_docs: list[str] = field(default_factory=list)
    type_sources: list[dict[str, str]] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)


def _require_field(obj: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in obj:
        raise SpecError(f"Missing required field '{key}' in {ctx}")
    return obj[key]


def _validate_examples(examples: list[dict[str, str]], signature: str) -> None:
    """Phase 9: optionally verify examples are shaped as function snippets.

    We perform a lightweight check: ensure each example function contains a
    `def <name>(` matching the signature's function name. This avoids strict
    parsing but catches obvious mismatches.
    """
    import re

    m = re.match(r"\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", signature)
    if not m:
        return
    fn_name = m.group(1)
    for idx, ex in enumerate(examples, start=1):
        func_text = str(ex.get("function", ""))
        if not func_text.strip():
            continue
        if f"def {fn_name}(" not in func_text:
            raise SpecError(f"Example {idx} function does not match signature name '{fn_name}'")


@lru_cache(maxsize=128)
def load_function_spec(name: str, start_path: Path | None = None) -> FunctionSpec:
    """Load a function spec YAML by name from `.splice/functions/<name>.yaml`."""

    base = require_splice_directory(start_path)
    spec_path = base / "functions" / f"{name}.yaml"
    if not spec_path.exists():
        raise SpecNotFoundError(f"Spec not found: {spec_path}")

    try:
        data: dict[str, Any] = yaml.safe_load(spec_path.read_text()) or {}
    except Exception as exc:  # pragma: no cover
        raise SpecError(f"Failed to parse spec at {spec_path}: {exc}") from exc

    # Basic validation
    if data.get("name") != name:
        raise SpecError("Spec 'name' must match the filename")

    contracts_obj = _require_field(data, "contracts", ctx=f"spec '{name}'")
    signature = _require_field(contracts_obj, "signature", ctx="contracts")
    inputs = _require_field(contracts_obj, "inputs", ctx="contracts")
    output = _require_field(contracts_obj, "output", ctx="contracts")
    if not isinstance(inputs, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in inputs.items()
    ):
        raise SpecError("contracts.inputs must be a map of name->type (strings)")
    if not isinstance(output, str) or not isinstance(signature, str):
        raise SpecError("contracts.signature and contracts.output must be strings")

    contracts = Contracts(
        signature=signature,
        inputs=dict(inputs),
        output=str(output),
        pydantic=dict(contracts_obj.get("pydantic", {})),
    )

    system_prompt = data.get("system_prompt")
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise SpecError("system_prompt must be a string if provided")

    context_docs = data.get("context_docs", [])
    if not isinstance(context_docs, list) or not all(isinstance(x, str) for x in context_docs):
        raise SpecError("context_docs must be a list of strings")

    type_sources = data.get("type_sources", [])
    if not isinstance(type_sources, list):
        raise SpecError("type_sources must be a list")

    examples = data.get("examples", [])
    if not isinstance(examples, list):
        raise SpecError("examples must be a list")

    # Phase 9: verify examples reference the correct function name
    try:
        _validate_examples(list(examples), signature)
    except SpecError:
        raise
    except Exception:
        # Non-fatal; only enforce clear mismatches
        pass

    return FunctionSpec(
        name=str(_require_field(data, "name", ctx="spec")),
        version=str(_require_field(data, "version", ctx="spec")),
        description=str(_require_field(data, "description", ctx="spec")),
        prompt=str(_require_field(data, "prompt", ctx="spec")),
        system_prompt=system_prompt,
        contracts=contracts,
        context_docs=list(context_docs),
        type_sources=list(type_sources),
        examples=list(examples),
    )


