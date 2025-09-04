from __future__ import annotations

from pathlib import Path
import time

from splice import Splice, Session
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
  repair: 0
"""
    )


class PerfClient:
    def generate_code(self, bundle, cfg):  # type: ignore[no-untyped-def]
        return (
            "def fast(a: int) -> int:\n"
            "    return a + 1\n"
        )


def test_cached_execution_is_fast(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    contracts = Contracts(signature="def fast(a: int) -> int:", inputs={"a": "int"}, output="int")
    spec = FunctionSpec(
        name="fast",
        version="0.0.1",
        description="",
        prompt="",
        system_prompt="def fast(a: int) -> int:",
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )
    _write_spec(tmp_path, spec)
    _write_config(tmp_path)

    import splice.client as client_mod
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: PerfClient())

    s = Session.ensure()
    sp = Splice()

    t0 = time.perf_counter()
    sp.run("fast", session=s, prompt="", start_path=tmp_path, a=1)  # generation + exec
    t1 = time.perf_counter()
    for _ in range(10):
        sp.run("fast", session=s, start_path=tmp_path, a=1)
    t2 = time.perf_counter()

    gen_ms = (t1 - t0) * 1000.0
    cached_ms = (t2 - t1) * 1000.0

    # Cached loop should be much faster than initial call
    assert cached_ms < gen_ms * 50


