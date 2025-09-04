## Phase 3 — OpenRouter client

### Build

- Minimal HTTP client that:
  - passes through `model.name`, `temperature`, and optional reasoning strength,
  - performs generation retries according to config,
  - extracts a Python function from fenced code blocks (```python ... ```),
  - avoids logging sensitive payloads.

### Runtime API

```python
from splice import SpliceConfig, OpenRouterClient, bundle_prompt

cfg = SpliceConfig.load()
bundle = bundle_prompt(spec, cfg, session_prompt="...")

client = OpenRouterClient()
code = client.generate_code(bundle, cfg)
```

Environment:

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

### Notes

- The client expects OpenAI-compatible responses from `chat/completions`.
- It extracts the first fenced Python block. If none is present, it returns the raw text trimmed.
- Future phases can add token-aware truncation and better provider metadata.


