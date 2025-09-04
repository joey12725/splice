from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from splice import Splice, Session
from splice.config import SpliceConfig, ModelConfig
from splice.specs import Contracts, FunctionSpec


def _write_spec(tmp_path: Path, name: str, spec: FunctionSpec) -> Path:
    base = tmp_path / ".splice" / "functions"
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{name}.yaml"
    import yaml

    data: dict[str, Any] = {
        "name": spec.name,
        "version": spec.version,
        "description": spec.description,
        "prompt": spec.prompt,
        "system_prompt": spec.system_prompt,
        "contracts": {
            "signature": spec.contracts.signature,
            "inputs": spec.contracts.inputs,
            "output": spec.contracts.output,
            "pydantic": spec.contracts.pydantic,
        },
        "context_docs": spec.context_docs,
        "type_sources": spec.type_sources,
        "examples": spec.examples,
    }
    p.write_text(yaml.safe_dump(data))
    return p


def _write_config(tmp_path: Path, db_path: str, ttl: str = "1s") -> Path:
    base = tmp_path / ".splice"
    base.mkdir(parents=True, exist_ok=True)
    cfg_path = base / "splice.yaml"
    cfg_path.write_text(
        f"""
model:
  name: openai/gpt-5-mini
  temperature: 0.0
  reasoning: 0
sessions:
  store: sqlite
  ttl: {ttl}
logging:
  database: {db_path}
sandbox:
  allow_imports: ["math"]
  allow_fs: false
  allow_net: false
  allow_subprocess: false
dependencies:
  policy: if-present
retries:
  generation: 0
  repair: 0
"""
    )
    return cfg_path


class FakeClientForCache:
    def __init__(self) -> None:
        self.calls = 0

    def generate_code(self, bundle, cfg):  # type: ignore[no-untyped-def]
        self.calls += 1
        # Return deterministic code for the signature in bundle's spec: we'll use a constant
        return (
            "def cached(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )


def test_cache_hit_skips_generation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    contracts = Contracts(signature="def cached(a: int, b: int) -> int:", inputs={"a": "int", "b": "int"}, output="int")
    spec = FunctionSpec(
        name="cached",
        version="0.0.1",
        description="",
        prompt="Compute a + b",
        system_prompt="def cached(a: int, b: int) -> int:",
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )
    _write_spec(tmp_path, "cached", spec)
    db_rel = "db.sqlite"
    _write_config(tmp_path, db_rel)

    # Swap client
    import splice.core as core
    import splice.client as client_mod
    fake = FakeClientForCache()
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: fake)

    s = Session.ensure()
    sp = Splice()
    # First call should generate
    out1 = sp.run("cached", session=s, prompt="Please add.", start_path=tmp_path, a=2, b=3)
    assert out1 == 5
    assert fake.calls == 1
    # Second call (no prompt) should hit cache, not call client again
    out2 = sp.run("cached", session=s, start_path=tmp_path, a=4, b=6)
    assert out2 == 10
    assert fake.calls == 1


def test_ttl_purge_evicts_artifact(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    contracts = Contracts(signature="def cached(a: int, b: int) -> int:", inputs={"a": "int", "b": "int"}, output="int")
    spec = FunctionSpec(
        name="cached",
        version="0.0.1",
        description="",
        prompt="Compute a + b",
        system_prompt="def cached(a: int, b: int) -> int:",
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )
    _write_spec(tmp_path, "cached", spec)
    db_rel = "db.sqlite"
    _write_config(tmp_path, db_rel, ttl="1s")

    import splice.client as client_mod
    fake = FakeClientForCache()
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: fake)

    s = Session.ensure()
    sp = Splice()
    out1 = sp.run("cached", session=s, prompt="Please add.", start_path=tmp_path, a=1, b=1)
    assert out1 == 2 and fake.calls == 1

    # Wait for TTL expiry
    import time
    time.sleep(1.1)

    # Next call should regenerate
    out2 = sp.run("cached", session=s, prompt="Please add.", start_path=tmp_path, a=1, b=2)
    assert out2 == 3
    assert fake.calls >= 2


