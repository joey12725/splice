from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .config import SpliceConfig
from .errors import SpliceError
from .prompt import PromptBundle


class GenerationError(SpliceError):
    """Raised when code generation fails or a valid function cannot be extracted."""


_CODE_FENCE_REGEX = re.compile(
    r"```(?:python)?\n([\s\S]*?)```",
    re.IGNORECASE,
)


def _extract_code_block(text: str) -> str:
    """Extract the first fenced Python code block; fallback to full text.

    The model is instructed to return exactly one function in a fenced block.
    If the fence is missing, we return the raw text trimmed.
    """

    match = _CODE_FENCE_REGEX.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


@dataclass
class OpenRouterClient:
    """Minimal client for OpenRouter chat completions (Phase 3).

    - Reads API key from environment variable `OPENROUTER_API_KEY` (or provided explicitly).
    - Passes through model name, temperature, and reasoning strength.
    - Retries per `config.retries.generation`.
    - Returns the extracted Python function string.
    """

    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"

    def _auth_headers(self) -> dict[str, str]:
        key = self.api_key or os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise GenerationError(
                "Missing OpenRouter API key. Set OPENROUTER_API_KEY in the environment."
            )
        return {
            "Authorization": f"Bearer {key}",
            # Optional but recommended headers for OpenRouter routing/quotas; safe defaults.
            "Content-Type": "application/json",
        }

    def generate_code(
        self,
        bundle: PromptBundle,
        config: SpliceConfig,
        *,
        request_timeout_seconds: float = 60.0,
        max_prompt_chars: int | None = None,
    ) -> str:
        """Generate code for the provided bundle and return the function string.

        Parameters
        ----------
        bundle: PromptBundle
            Assembled prompt text from Phase 2.
        config: SpliceConfig
            Global config providing model name/params and retry policy.
        request_timeout_seconds: float
            Network timeout per request.
        max_prompt_chars: Optional[int]
            If set, truncate the bundle text to this many characters to avoid token limits.
        """

        text = bundle.text
        if max_prompt_chars is not None and max_prompt_chars > 0 and len(text) > max_prompt_chars:
            text = text[-max_prompt_chars:]

        payload: dict[str, Any] = {
            "model": config.model.name,
            "temperature": config.model.temperature,
            # Some OpenRouter providers accept reasoning; pass through if present.
            "messages": [
                {"role": "user", "content": text},
            ],
        }

        # A few providers require this field with enum values
        # Map numeric strengths to valid enums; allow direct string passthrough
        reasoning_strength = getattr(config.model, "reasoning", None)
        effort_value: Optional[str] = None
        if isinstance(reasoning_strength, str):
            lowered = reasoning_strength.lower().strip()
            if lowered in {"minimal", "low", "medium", "high"}:
                effort_value = lowered
        elif isinstance(reasoning_strength, (int, float)):
            if reasoning_strength <= 0:
                effort_value = None
            elif reasoning_strength < 2:
                effort_value = "low"
            elif reasoning_strength < 3:
                effort_value = "medium"
            else:
                effort_value = "high"
        if effort_value:
            payload["reasoning"] = {"effort": effort_value}

        attempts = max(int(config.retries.generation), 0) + 1
        last_error: Exception | None = None

        headers = self._auth_headers()

        with httpx.Client(base_url=self.base_url, headers=headers, timeout=request_timeout_seconds) as client:
            for _ in range(attempts):
                try:
                    resp = client.post("/chat/completions", json=payload)
                    if resp.status_code >= 500:
                        last_error = GenerationError(
                            f"OpenRouter server error {resp.status_code}: {resp.text[:200]}"
                        )
                        continue
                    if resp.status_code != 200:
                        # 4xx/others are not retried unless more attempts remain
                        raise GenerationError(
                            f"OpenRouter request failed {resp.status_code}: {resp.text[:200]}"
                        )

                    data = resp.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise GenerationError("No choices returned by OpenRouter")
                    content = (
                        (choices[0].get("message") or {}).get("content")
                        or choices[0].get("text")
                    )
                    if not isinstance(content, str) or not content.strip():
                        raise GenerationError("Empty completion content from OpenRouter")

                    code = _extract_code_block(content)
                    if not code:
                        raise GenerationError("Failed to extract code block from model response")
                    return code
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    continue
                except GenerationError as exc:
                    last_error = exc
                    continue

        # Exhausted retries
        if last_error:
            raise GenerationError(str(last_error))
        raise GenerationError("Unknown error during code generation")



    def complete_text(
        self,
        messages: list[dict[str, str]],
        config: SpliceConfig,
        *,
        request_timeout_seconds: float = 60.0,
        max_prompt_chars: int | None = None,
    ) -> str:
        """Generic chat completion that returns raw text.

        Parameters
        ----------
        messages: list[dict[str, str]]
            Chat messages to send. Each entry should be like {"role": "system|user|assistant", "content": str}.
        config: SpliceConfig
            Global config providing model name/params and retry policy.
        request_timeout_seconds: float
            Network timeout per request.
        max_prompt_chars: Optional[int]
            If set, truncates the content of the longest message to this many characters to avoid token limits.
        """

        # Optionally truncate only the largest content to avoid surprising prompt loss
        if max_prompt_chars is not None and max_prompt_chars > 0:
            # Find the longest content field and truncate from the end (most recent context)
            longest_idx: int | None = None
            longest_len = -1
            for idx, m in enumerate(messages):
                c = str(m.get("content", ""))
                if len(c) > longest_len:
                    longest_len = len(c)
                    longest_idx = idx
            if longest_idx is not None and longest_len > max_prompt_chars:
                m = dict(messages[longest_idx])
                m["content"] = str(m.get("content", ""))[-max_prompt_chars:]
                messages = list(messages)
                messages[longest_idx] = m

        payload: dict[str, Any] = {
            "model": config.model.name,
            "temperature": config.model.temperature,
            "messages": messages,
        }

        reasoning_strength = getattr(config.model, "reasoning", None)
        effort_value: Optional[str] = None
        if isinstance(reasoning_strength, str):
            lowered = reasoning_strength.lower().strip()
            if lowered in {"minimal", "low", "medium", "high"}:
                effort_value = lowered
        elif isinstance(reasoning_strength, (int, float)):
            if reasoning_strength <= 0:
                effort_value = None
            elif reasoning_strength < 2:
                effort_value = "low"
            elif reasoning_strength < 3:
                effort_value = "medium"
            else:
                effort_value = "high"
        if effort_value:
            payload["reasoning"] = {"effort": effort_value}

        attempts = max(int(config.retries.generation), 0) + 1
        last_error: Exception | None = None

        headers = self._auth_headers()

        with httpx.Client(base_url=self.base_url, headers=headers, timeout=request_timeout_seconds) as client:
            for _ in range(attempts):
                try:
                    resp = client.post("/chat/completions", json=payload)
                    if resp.status_code >= 500:
                        last_error = GenerationError(
                            f"OpenRouter server error {resp.status_code}: {resp.text[:200]}"
                        )
                        continue
                    if resp.status_code != 200:
                        # 4xx/others are not retried unless more attempts remain
                        raise GenerationError(
                            f"OpenRouter request failed {resp.status_code}: {resp.text[:200]}"
                        )

                    data = resp.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise GenerationError("No choices returned by OpenRouter")
                    content = (
                        (choices[0].get("message") or {}).get("content")
                        or choices[0].get("text")
                    )
                    if not isinstance(content, str) or not content.strip():
                        raise GenerationError("Empty completion content from OpenRouter")
                    return content.strip()
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    continue
                except GenerationError as exc:
                    last_error = exc
                    continue

        if last_error:
            raise GenerationError(str(last_error))
        raise GenerationError("Unknown error during text completion")

