# Phase 2 — Prompt Bundler

Phase 2 introduces a deterministic prompt bundler that assembles the exact text sent to the model from the config, function spec, session prompt, context docs, and examples.

## Goals
- Deterministic assembly (stable order, no hidden state)
- Clear precedence: spec-level `system_prompt` overrides global config; session prompt overrides spec `prompt`
- Strict instruction to return exactly one Python function (no prose)

## What it builds
- `splice.prompt.bundle_prompt(spec, config, session_prompt=None, start_path=None) -> PromptBundle`
  - Respects system prompt precedence
  - Includes contracts (signature, inputs, output)
  - Loads context docs from `.splice/context/*.md` referenced by `spec.context_docs`
  - Includes examples as few-shot pairs (`prompt` + fenced Python `function`)
  - Appends a final strict instruction

## Output structure
The bundle is a single text blob with sections in this order:
1. SYSTEM PROMPT
2. CONTRACT SIGNATURE (fenced)
3. CONTRACT TYPES (inputs/output)
4. CONTEXT DOCS (optional; each doc included as-is)
5. TASK PROMPT (session-scoped)
6. EXAMPLES (optional; few-shot)
7. FINAL INSTRUCTION (strict one-function rule)

## API
```python
from splice import SpliceConfig
from splice import bundle_prompt

cfg = SpliceConfig.load()  # or construct directly
spec = ...  # load via splice.spec("name") or load_function_spec("name")

bundle = bundle_prompt(spec, cfg, session_prompt="Compute a + b", start_path=None)
print(bundle.text)
```

## Context docs
- Docs are read from `.splice/context/`. Each entry in `spec.context_docs` may be `Name` or `Name.md`.
- Missing or unreadable docs are skipped silently in Phase 2.

## Examples in specs
- Examples are provided as a list of objects with `prompt` and `function` (Python fenced in output).

## Tests
- See `tests/test_prompt_bundler.py` for cases covering system prompt precedence, session prompt override, contracts, context docs, and examples inclusion.

## Exit criteria
- Given a spec + prompt, `bundle_prompt` returns a stable text bundle with the sections listed above and correct precedence.


