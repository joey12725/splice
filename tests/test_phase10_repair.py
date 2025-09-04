from __future__ import annotations

from pathlib import Path

from splice import Splice, Session
from splice.config import SpliceConfig, RetriesConfig
from splice.specs import FunctionSpec, Contracts


def _write_spec(tmp_path: Path, spec: FunctionSpec) -> None:
    base = tmp_path / ".splice" / "functions"
    base.mkdir(parents=True, exist_ok=True)
    import yaml
    data = {
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
    (base / f"{spec.name}.yaml").write_text(yaml.safe_dump(data))


def _write_config(tmp_path: Path) -> None:
    base = tmp_path / ".splice"
    base.mkdir(parents=True, exist_ok=True)
    (base / "splice.yaml").write_text(
        """
model:
  name: openai/gpt-5-mini
  temperature: 0.0
  reasoning: 0
sessions:
  store: sqlite
  ttl: 1h
logging:
  database: db.sqlite
sandbox:
  allow_imports: ["math"]
  allow_fs: false
  allow_net: false
  allow_subprocess: false
dependencies:
  policy: if-present
retries:
  generation: 0
  repair: 1
"""
    )


class ClientThatRepairs:
    def __init__(self) -> None:
        self.calls = 0

    def generate_code(self, bundle, cfg):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            # Return code that fails at runtime
            return (
                "def boom(a: int, b: int) -> int:\n"
                "    return 1/0\n"
            )
        # Second call returns working code
        return (
            "def boom(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )


def test_auto_repair_executes_second_attempt(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    contracts = Contracts(signature="def boom(a: int, b: int) -> int:", inputs={"a": "int", "b": "int"}, output="int")
    spec = FunctionSpec(
        name="boom",
        version="0.0.1",
        description="",
        prompt="",
        system_prompt="def boom(a: int, b: int) -> int:",
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )
    _write_spec(tmp_path, spec)
    _write_config(tmp_path)

    import splice.client as client_mod
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: ClientThatRepairs())

    s = Session.ensure()
    sp = Splice()
    # Auto-repair within a single call should succeed
    out = sp.run("boom", session=s, prompt="", start_path=tmp_path, a=1, b=2)
    assert out == 3


