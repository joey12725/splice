from __future__ import annotations

import textwrap
from pathlib import Path

from splice.config import ModelConfig, SpliceConfig
from splice.prompt import bundle_prompt
from splice.specs import Contracts, FunctionSpec


def make_spec(**overrides):
    contracts = Contracts(
        signature="def add(a: int, b: int) -> int:",
        inputs={"a": "int", "b": "int"},
        output="int",
        pydantic={},
    )
    spec = FunctionSpec(
        name="adder",
        version="1.0.0",
        description="Add two integers",
        prompt="Write a function to add two integers.",
        system_prompt=None,
        contracts=contracts,
        context_docs=["Math"],
        type_sources=[],
        examples=[
            {
                "prompt": "Add 2 and 3",
                "function": textwrap.dedent(
                    """
                    def add(a: int, b: int) -> int:
                        return a + b
                    """
                ).strip(),
            }
        ],
    )
    for k, v in overrides.items():
        setattr(spec, k, v)
    return spec


def write_context(tmp_path: Path, name: str, content: str) -> Path:
    base = tmp_path / ".splice" / "context"
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{name}.md"
    p.write_text(content)
    return p


def test_system_prompt_precedence_tmp(tmp_path: Path):
    write_context(tmp_path, "Math", "# Math\nBasic arithmetic.")

    cfg = SpliceConfig(model=ModelConfig(system_prompt="DEFAULT SYSTEM"))
    spec = make_spec(system_prompt="SPEC SYSTEM")

    bundle = bundle_prompt(spec, cfg, start_path=tmp_path)
    text = bundle.text

    assert "SYSTEM PROMPT:" in text
    assert "SPEC SYSTEM" in text
    assert "DEFAULT SYSTEM" not in text


def test_session_prompt_overrides_spec_prompt(tmp_path: Path):
    write_context(tmp_path, "Math", "# Math\nBasic arithmetic.")

    cfg = SpliceConfig(model=ModelConfig(system_prompt="DEFAULT SYSTEM"))
    spec = make_spec()

    bundle = bundle_prompt(spec, cfg, session_prompt="SESSION TASK", start_path=tmp_path)
    text = bundle.text

    assert "TASK PROMPT:" in text
    assert "SESSION TASK" in text
    assert "Write a function to add two integers." not in text


def test_includes_contracts_and_examples_and_context(tmp_path: Path):
    write_context(tmp_path, "Math", "Docs about math.")

    cfg = SpliceConfig(model=ModelConfig(system_prompt="DEFAULT SYSTEM"))
    spec = make_spec()

    bundle = bundle_prompt(spec, cfg, start_path=tmp_path)
    text = bundle.text

    # Contracts
    assert "def add(a: int, b: int) -> int:" in text
    assert "- a: int" in text and "- b: int" in text
    assert "- int" in text

    # Context docs
    assert "CONTEXT DOCS:" in text
    assert "Math.md" in text
    assert "Docs about math." in text

    # Examples
    assert "EXAMPLES:" in text
    assert "Example 1 — Prompt:" in text
    assert "Add 2 and 3" in text
    assert "```python" in text
    assert "def add(a: int, b: int) -> int:" in text
