from __future__ import annotations

import os
from typing import Any, ClassVar

import httpx
import pytest

from splice.client import GenerationError, OpenRouterClient
from splice.config import RetriesConfig, SpliceConfig
from splice.prompt import PromptBundle


class FakeResponse:
    def __init__(
        self, status_code: int, json_data: dict[str, Any] | None = None, text: str = ""
    ) -> None:
        self._status_code = status_code
        self._json_data = json_data or {}
        self._text = text

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def text(self) -> str:
        return self._text

    def json(self) -> dict[str, Any]:
        return self._json_data


class FakeClient:
    """Drop-in replacement for httpx.Client used by tests via monkeypatch."""

    # Captured instances for assertions
    created_instances: ClassVar[list[FakeClient]] = []

    # Pre-seeded responses to return per POST call
    next_responses: ClassVar[list[FakeResponse]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._response_idx = 0
        FakeClient.created_instances.append(self)

    # Context manager protocol
    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False

    # POST method the client under test will call
    def post(self, path: str, json: dict[str, Any]) -> FakeResponse:
        self.calls.append((path, json))
        if FakeClient.next_responses:
            # Pop from front to simulate sequential responses
            resp = FakeClient.next_responses.pop(0)
            return resp
        # Default: OK empty
        return FakeResponse(200, json_data={"choices": [{"message": {"content": ""}}]})


def _set_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # Replace httpx.Client with our FakeClient class
    monkeypatch.setattr(httpx, "Client", FakeClient)
    # Reset captured state for each test
    FakeClient.created_instances.clear()
    FakeClient.next_responses.clear()


def _ok_choices_with_content(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


def test_generate_code_extracts_fenced_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_client(monkeypatch)

    code_text = """```python\ndef foo(a: int, b: int) -> int:\n    return a + b\n```"""
    FakeClient.next_responses.append(
        FakeResponse(200, json_data=_ok_choices_with_content(code_text))
    )

    cfg = SpliceConfig()
    bundle = PromptBundle(text="SOME PROMPT")
    client = OpenRouterClient(api_key="test-key")

    code = client.generate_code(bundle, cfg)
    assert code.startswith("def foo(")
    assert "return a + b" in code


def test_generate_code_fallback_without_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_client(monkeypatch)

    raw = "def bar(x):\n    return x * 2\n"
    FakeClient.next_responses.append(FakeResponse(200, json_data=_ok_choices_with_content(raw)))

    cfg = SpliceConfig()
    bundle = PromptBundle(text="SOME PROMPT")
    client = OpenRouterClient(api_key="test-key")

    code = client.generate_code(bundle, cfg)
    assert code.strip().startswith("def bar(")
    assert "return x * 2" in code


def test_retries_on_server_error_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_client(monkeypatch)

    # First 500, then 200 OK with code
    FakeClient.next_responses.append(FakeResponse(500, text="upstream error"))
    FakeClient.next_responses.append(
        FakeResponse(
            200, json_data=_ok_choices_with_content("""```python\ndef baz():\n    return 42\n```""")
        )
    )

    cfg = SpliceConfig(retries=RetriesConfig(generation=1, repair=0))  # 1 retry => 2 total attempts
    bundle = PromptBundle(text="PROMPT")
    client = OpenRouterClient(api_key="test-key")

    code = client.generate_code(bundle, cfg)
    assert code.strip().startswith("def baz(")

    # Ensure we attempted twice
    assert FakeClient.created_instances, "Fake client was not constructed"
    calls = FakeClient.created_instances[0].calls
    assert len(calls) == 2
    # Validate payload basics
    _, payload = calls[0]
    assert payload.get("model") == cfg.model.name
    assert payload.get("temperature") == cfg.model.temperature
    assert isinstance(payload.get("messages"), list) and payload["messages"], "messages missing"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_fake_client(monkeypatch)
    # Save and clear env var
    original_key = os.environ.get("OPENROUTER_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    try:
        cfg = SpliceConfig()
        bundle = PromptBundle(text="PROMPT")
        client = OpenRouterClient(api_key=None)

        with pytest.raises(GenerationError):
            client.generate_code(bundle, cfg)
    finally:
        # Restore original key to avoid losing it for subsequent tests
        if original_key is not None:
            monkeypatch.setenv("OPENROUTER_API_KEY", original_key)
        else:
            monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
