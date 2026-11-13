from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from splice.config import ConfigError, SpliceConfig
from splice.specs import SpecError, load_function_spec


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"))


def test_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No file present -> defaults
    monkeypatch.chdir(tmp_path)
    cfg = SpliceConfig.load()
    assert cfg.model.name == "openai/gpt-5-mini"
    assert cfg.sessions.store == "sqlite"
    assert cfg.logging.database == ".splice/db.sqlite"


def test_config_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_file(
        tmp_path / ".splice/splice.yaml",
        """
        model:
          name: openai/gpt-5-mini
          temperature: 0.3
        sessions:
          store: sqlite
          ttl: 48h
        dependencies:
          policy: if-present
        """,
    )
    cfg = SpliceConfig.load()
    assert cfg.model.temperature == 0.3
    assert cfg.sessions.ttl == "48h"
    assert cfg.dependencies.policy == "if-present"


def test_config_validation_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_file(
        tmp_path / ".splice/splice.yaml",
        """
        sessions:
          store: bad-store
        """,
    )
    with pytest.raises(ConfigError):
        SpliceConfig.load()


def test_spec_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_file(
        tmp_path / ".splice/functions/generic_operand.yaml",
        """
        name: generic_operand
        version: 0.1.0
        description: Simple calc
        prompt: default prompt
        contracts:
          signature: "def generic_operand(a: float, b: float) -> float"
          inputs:
            a: float
            b: float
          output: float
        context_docs: []
        type_sources: []
        examples: []
        """,
    )
    spec = load_function_spec("generic_operand")
    assert spec.name == "generic_operand"
    assert spec.contracts.inputs["a"] == "float"


def test_spec_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_file(
        tmp_path / ".splice/functions/bad.yaml",
        """
        name: mismatch
        version: 0.1.0
        description: Bad
        prompt: p
        contracts:
          signature: s
          inputs: []
          output: o
        """,
    )
    with pytest.raises(SpecError):
        load_function_spec("bad")
