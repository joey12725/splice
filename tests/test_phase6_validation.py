from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from splice import Splice, Session
from splice.specs import FunctionSpec, Contracts
from splice.errors import ValidationError


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
        textwrap.dedent(
            """
            model:
              name: openai/gpt-5-mini
              temperature: 0.0
              reasoning: 0
            sessions:
              store: sqlite
              ttl: 24h
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
        ).strip()
        + "\n"
    )


class FakeClient:
    def generate_code(self, bundle, cfg):  # type: ignore[no-untyped-def]
        return (
            "def typed(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )


def test_input_type_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    contracts = Contracts(
        signature="def typed(a: int, b: int) -> int:",
        inputs={"a": "int", "b": "int"},
        output="int",
        pydantic={},
    )
    spec = FunctionSpec(
        name="typed",
        version="0.0.1",
        description="",
        prompt="",
        system_prompt="def typed(a: int, b: int) -> int:",
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )
    _write_spec(tmp_path, spec)
    _write_config(tmp_path)

    import splice.client as client_mod
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: FakeClient())

    s = Session.ensure()
    sp = Splice()

    # ok types
    out = sp.run("typed", session=s, prompt="", start_path=tmp_path, a=1, b=2)
    assert out == 3

    # wrong type for a
    with pytest.raises(ValidationError):
        sp.run("typed", session=s, prompt="", start_path=tmp_path, a="1", b=2)  # type: ignore[arg-type]


def test_output_type_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    contracts = Contracts(
        signature="def typed(a: int) -> int:",
        inputs={"a": "int"},
        output="int",
        pydantic={},
    )
    spec = FunctionSpec(
        name="typed",
        version="0.0.1",
        description="",
        prompt="",
        system_prompt="def typed(a: int) -> int:",
        contracts=contracts,
        context_docs=[],
        type_sources=[],
        examples=[],
    )
    _write_spec(tmp_path, spec)
    _write_config(tmp_path)

    class ClientBadOut:
        def generate_code(self, bundle, cfg):  # type: ignore[no-untyped-def]
            return (
                "def typed(a: int) -> int:\n"
                "    return str(a)\n"
            )

    import splice.client as client_mod
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: ClientBadOut())

    s = Session.ensure()
    sp = Splice()

    with pytest.raises(ValidationError):
        sp.run("typed", session=s, prompt="", start_path=tmp_path, a=1)


