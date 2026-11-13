"""OpenRouter chat-completions client used for code and doc generation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import SpliceConfig
from .errors import GenerationError
from .prompt import PromptBundle

__all__ = ["GenerationError", "OpenRouterClient"]

_CODE_FENCE_REGEX = re.compile(r"```(?:python|py)?[ \t]*\n([\s\S]*?)```", re.IGNORECASE)
_EFFORT_LEVELS = ("minimal", "low", "medium", "high")


def _extract_code_block(text: str) -> str:
    """Return the first fenced code block in ``text``, or the whole text trimmed."""

    match = _CODE_FENCE_REGEX.search(text)
    return (match.group(1) if match else text).strip()


def _reasoning_effort(strength: Any) -> str | None:
    """Map ``model.reasoning`` (0-3 or a level name) to an OpenRouter effort value."""

    if isinstance(strength, str):
        lowered = strength.lower().strip()
        return lowered if lowered in _EFFORT_LEVELS else None
    if isinstance(strength, (int, float)) and not isinstance(strength, bool):
        if strength <= 0:
            return None
        if strength < 2:
            return "low"
        if strength < 3:
            return "medium"
        return "high"
    return None


@dataclass
class OpenRouterClient:
    """Minimal OpenRouter client.

    * Reads the API key from ``OPENROUTER_API_KEY`` unless one is passed in.
    * Passes through model name, temperature and reasoning effort.
    * Retries transport errors and 5xx responses ``retries.generation`` times.
    """

    api_key: str | None = None
    base_url: str = "https://openrouter.ai/api/v1"

    def _auth_headers(self) -> dict[str, str]:
        key = self.api_key or os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise GenerationError(
                "Missing OpenRouter API key. Set OPENROUTER_API_KEY in the environment."
            )
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _payload(self, messages: list[dict[str, str]], config: SpliceConfig) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": config.model.name,
            "temperature": config.model.temperature,
            "messages": messages,
        }
        effort = _reasoning_effort(getattr(config.model, "reasoning", None))
        if effort:
            payload["reasoning"] = {"effort": effort}
        return payload

    def _complete(self, payload: dict[str, Any], config: SpliceConfig, timeout: float) -> str:
        """POST ``payload`` with retries and return the first choice's text."""

        attempts = max(int(config.retries.generation), 0) + 1
        last_error: Exception | None = None
        headers = self._auth_headers()
        with httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout) as client:
            for _ in range(attempts):
                try:
                    resp = client.post("/chat/completions", json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    continue
                if resp.status_code >= 500 or resp.status_code in (408, 429):
                    last_error = GenerationError(
                        f"OpenRouter error {resp.status_code}: {resp.text[:200]}"
                    )
                    continue
                if resp.status_code != 200:
                    # Other 4xx (bad key, bad model, bad request) will not improve on retry.
                    raise GenerationError(
                        f"OpenRouter request failed {resp.status_code}: {resp.text[:200]}"
                    )
                choices = (resp.json() or {}).get("choices") or []
                if not choices:
                    last_error = GenerationError("No choices returned by OpenRouter")
                    continue
                first = choices[0]
                content = (first.get("message") or {}).get("content") or first.get("text")
                if not isinstance(content, str) or not content.strip():
                    last_error = GenerationError("Empty completion content from OpenRouter")
                    continue
                return content
        raise GenerationError(str(last_error) if last_error else "Unknown error from OpenRouter")

    def generate_code(
        self,
        bundle: PromptBundle,
        config: SpliceConfig,
        *,
        request_timeout_seconds: float = 60.0,
        max_prompt_chars: int | None = None,
    ) -> str:
        """Generate code for ``bundle`` and return the extracted function source.

        ``max_prompt_chars`` keeps only the tail of an oversized prompt.
        """

        text = bundle.text
        if max_prompt_chars and len(text) > max_prompt_chars:
            text = text[-max_prompt_chars:]
        payload = self._payload([{"role": "user", "content": text}], config)
        code = _extract_code_block(self._complete(payload, config, request_timeout_seconds))
        if not code:
            raise GenerationError("Failed to extract code block from model response")
        return code

    def complete_text(
        self,
        messages: list[dict[str, str]],
        config: SpliceConfig,
        *,
        request_timeout_seconds: float = 60.0,
        max_prompt_chars: int | None = None,
    ) -> str:
        """Generic chat completion returning raw text.

        ``max_prompt_chars`` truncates the longest message (keeping its tail).
        """

        if max_prompt_chars and messages:
            idx = max(range(len(messages)), key=lambda i: len(str(messages[i].get("content", ""))))
            content = str(messages[idx].get("content", ""))
            if len(content) > max_prompt_chars:
                messages = list(messages)
                messages[idx] = {**messages[idx], "content": content[-max_prompt_chars:]}
        payload = self._payload(messages, config)
        return self._complete(payload, config, request_timeout_seconds).strip()
