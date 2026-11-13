"""End-to-end tests for Splice.run with a scripted (offline) code generator."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from splice import (
    PromptRequiredError,
    SandboxViolation,
    Session,
    Splice,
    ValidationError,
)
from splice.config import SpliceConfig
from splice.prompt import PromptBundle
from splice.store import ArtifactStore

CONFIG = """\
model:
  name: test/model
  temperature: 0.0
sessions:
  ttl: {ttl}
logging:
  database: db.sqlite
sandbox:
  backend: process
  allow_imports: ["math"]
retries:
  generation: 0
  repair: {repair}
"""


class ScriptedClient:
    """Returns canned code in order; records every prompt it sees."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    def generate_code(self, bundle: PromptBundle, config: SpliceConfig) -> str:
        self.prompts.append(bundle.text)
        return self.responses[min(len(self.prompts), len(self.responses)) - 1]


Workspace = Callable[..., Path]


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    def make(
        name: str = "add",
        signature: str = "def add(a: int, b: int) -> int",
        inputs: dict[str, str] | None = None,
        output: str = "int",
        ttl: str = "1h",
        repair: int = 0,
    ) -> Path:
        base = tmp_path / ".splice"
        (base / "functions").mkdir(parents=True, exist_ok=True)
        (base / "splice.yaml").write_text(CONFIG.format(ttl=ttl, repair=repair))
        spec = {
            "name": name,
            "version": "0.1.0",
            "description": "",
            "prompt": "",
            "contracts": {
                "signature": signature,
                "inputs": inputs if inputs is not None else {"a": "int", "b": "int"},
                "output": output,
            },
        }
        (base / "functions" / f"{name}.yaml").write_text(yaml.safe_dump(spec))
        return tmp_path

    return make


ADD = "def add(a: int, b: int) -> int:\n    return a + b\n"


def run(sp: Splice, root: Path, session: Session, **kwargs: Any) -> Any:
    name = kwargs.pop("name", "add")
    return sp.run(name, session=session, start_path=root, **kwargs)


def test_generates_once_then_serves_from_cache(workspace: Workspace) -> None:
    root = workspace()
    client = ScriptedClient(ADD)
    sp, s = Splice(client=client), Session.ensure()

    assert run(sp, root, s, prompt="Add them", a=2, b=3) == 5
    assert run(sp, root, s, a=4, b=6) == 10
    assert run(sp, root, s, a=-1, b=1) == 0
    assert client.calls == 1


def test_sessions_are_isolated(workspace: Workspace) -> None:
    root = workspace()
    client = ScriptedClient(ADD)
    sp = Splice(client=client)
    run(sp, root, Session.ensure(), prompt="Add them", a=1, b=1)
    with pytest.raises(PromptRequiredError):
        run(sp, root, Session.ensure(), a=1, b=1)


def test_spec_change_invalidates_cache(workspace: Workspace) -> None:
    root = workspace()
    client = ScriptedClient(ADD)
    sp, s = Splice(client=client), Session.ensure()
    run(sp, root, s, prompt="Add them", a=1, b=1)
    spec_path = root / ".splice" / "functions" / "add.yaml"
    spec_path.write_text(spec_path.read_text().replace("version: 0.1.0", "version: 0.2.0"))
    run(sp, root, s, prompt="Add them", a=1, b=1)
    assert client.calls == 2


def test_ttl_expiry_regenerates(workspace: Workspace) -> None:
    root = workspace(ttl="1s")
    client = ScriptedClient(ADD)
    sp, s = Splice(client=client), Session.ensure()
    run(sp, root, s, prompt="Add them", a=1, b=1)
    time.sleep(1.1)
    assert run(sp, root, s, prompt="Add them", a=1, b=2) == 3
    assert client.calls == 2


def test_generate_only_mode(workspace: Workspace) -> None:
    root = workspace()
    client = ScriptedClient(ADD)
    sp, s = Splice(client=client), Session.ensure()
    assert run(sp, root, s, prompt="Add them", run_now=False) is None
    assert client.calls == 1
    assert run(sp, root, s, a=20, b=22) == 42
    assert client.calls == 1


def test_generate_only_without_prompt_warns(workspace: Workspace) -> None:
    root = workspace()
    sp = Splice(client=ScriptedClient(ADD))
    with pytest.warns(UserWarning):
        assert run(sp, root, Session.ensure(), run_now=False) is None


def test_prompt_required_on_first_call(workspace: Workspace) -> None:
    root = workspace()
    with pytest.raises(PromptRequiredError):
        run(Splice(client=ScriptedClient(ADD)), root, Session.ensure(), a=1, b=2)


def test_repair_loop_fixes_runtime_error(workspace: Workspace) -> None:
    root = workspace(repair=1)
    broken = "def add(a: int, b: int) -> int:\n    return 1 / 0\n"
    client = ScriptedClient(broken, ADD)
    assert run(Splice(client=client), root, Session.ensure(), prompt="Add", a=1, b=2) == 3
    assert client.calls == 2
    assert "ZeroDivisionError" in client.prompts[1]


def test_repair_loop_recovers_from_sandbox_violation(workspace: Workspace) -> None:
    root = workspace(repair=1)
    sneaky = "import os\ndef add(a: int, b: int) -> int:\n    return a + b\n"
    client = ScriptedClient(sneaky, ADD)
    assert run(Splice(client=client), root, Session.ensure(), prompt="Add", a=1, b=2) == 3
    assert "SandboxViolation" in client.prompts[1]


def test_violation_surfaces_when_repairs_exhausted(workspace: Workspace) -> None:
    root = workspace(repair=0)
    sneaky = "import os\ndef add(a: int, b: int) -> int:\n    return a + b\n"
    with pytest.raises(SandboxViolation):
        run(Splice(client=ScriptedClient(sneaky)), root, Session.ensure(), prompt="Add", a=1, b=2)


def test_input_validation(workspace: Workspace) -> None:
    root = workspace()
    sp, s = Splice(client=ScriptedClient(ADD)), Session.ensure()
    with pytest.raises(ValidationError):
        run(sp, root, s, prompt="Add", a="1", b=2)


def test_output_validation(workspace: Workspace) -> None:
    root = workspace()
    bad = "def add(a: int, b: int) -> int:\n    return str(a + b)\n"
    with pytest.raises(ValidationError):
        run(Splice(client=ScriptedClient(bad)), root, Session.ensure(), prompt="Add", a=1, b=2)


def test_events_are_logged(workspace: Workspace) -> None:
    root = workspace()
    run(Splice(client=ScriptedClient(ADD)), root, Session.ensure(), prompt="Add", a=1, b=2)
    kinds = [kind for _, kind, *_ in ArtifactStore(start_path=root).list_events()]
    assert kinds[:2] == ["generation_requested", "generation_succeeded"]
    assert "execution_succeeded" in kinds


def test_default_database_lives_in_workspace(tmp_path: Path) -> None:
    from splice.store import resolve_database_path

    base = tmp_path / ".splice"
    assert resolve_database_path(SpliceConfig(), base) == (base / "db.sqlite").resolve()


def test_client_is_patchable_for_legacy_callers(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import splice.client as client_mod

    client = ScriptedClient(ADD)
    monkeypatch.setattr(client_mod, "OpenRouterClient", lambda *a, **k: client)
    assert run(Splice(), workspace(), Session.ensure(), prompt="Add", a=1, b=2) == 3
    assert client.calls == 1
