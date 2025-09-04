# Splice

Session-scoped LLM code executor for Python with sandboxed execution, deterministic prompts, and per-session caching. Build features that generate code once and reuse it many times.

## Features
- Deterministic prompt bundling from config, spec, context docs, and examples
- Sandboxed execution with import allowlist and gated FS/NET/subprocess
- Session-scoped cache in SQLite keyed by spec/context/config/prompt
- Simple YAML specs for function contracts (signature, types, examples)
- Minimal CLI for init, scaffolding, doc generation, and cache management
- Optional dependency policy and per-session virtualenvs

## Install

```bash
pip install -e '.[dev]'
```

## Environment
Set your OpenRouter API key (do not hardcode):

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

## Quickstart

CLI:
```bash
# 1) Initialize workspace
splice init

# 2) Create a function spec skeleton
splice edit --add-func my_op

# 3) (Optional) Generate docs for types/classes into .splice/context
splice edit --doc-class collections.Counter datetime.datetime
```

Code:
```python
from splice import Splice, Session

session = Session.ensure()
result = Splice().run(
    "my_op",
    session=session,
    prompt="Return (a + b) / 2",
    a=4.0,
    b=6.0,
)
print(result)
```

Generate-only (no execution) when you don't have test data yet:
```python
from splice import Splice, Session

session = Session.ensure()
# Generates and caches code, but does not execute and returns None
Splice().run(
    "my_op",
    session=session,
    prompt="Return (a + b) / 2",
    run_now=False,
)
# Later, call without run_now to actually execute; auto-repair still applies
print(Splice().run("my_op", session=session, a=4.0, b=6.0))
```

## Function specs (YAML)
Place specs at `.splice/functions/<name>.yaml`.

Minimal example:
```yaml
name: my_op
version: 0.1.0
description: Example op
prompt: Return (a + b) / 2
system_prompt: |
  You are a code generator. Output exactly one valid Python function that
  matches the declared signature and contracts. No explanations.
contracts:
  signature: "def my_op(a: float, b: float) -> float"
  inputs:
    a: float
    b: float
  output: float
context_docs: []
type_sources: []
examples: []
```

## CLI overview
- `splice init [--wizard]` — create `.splice/` with `functions/`, `context/`, and default `splice.yaml`
- `splice edit` — unified editor for config, functions, and docs
  - `--add-func <name> [more...]`, `--func-mode [minimal|auto]`
  - `--doc-class <Import.Path> [More.Paths...]`
  - `--doc-url <URL> --doc-url-name <Name>`
  - Config: `--set-model`, `--set-system-prompt-text|--set-system-prompt-file`, `--set-reasoning`,
    `--set-sandbox-imports`, `--enable-*/--disable-*`, `--set-deps-policy`, `--set-retries-*`
- `splice cache purge` — clear cached artifacts
- `splice --version` — print installed version

## Configuration
Global config lives in `.splice/splice.yaml`. If missing, sensible defaults are used.

Example:
```yaml
model:
  name: openai/gpt-5-mini
  temperature: 0.2
  reasoning: 1
  system_prompt: |
    You are a code generator. Output exactly one valid Python function that
    matches the declared signature and contracts. No explanations.

sessions:
  store: sqlite
  ttl: 24h

logging:
  database: .splice/db.sqlite

sandbox:
  allow_imports: ["math", "statistics", "numpy"]
  allow_fs: false
  allow_net: false
  allow_subprocess: false

dependencies:
  policy: if-present  # off | if-present | allow

retries:
  generation: 2
  repair: 1
```

## Developer docs
See the developer documentation in `docs/`:

- `docs/index.md` — overview and navigation
- `docs/guide/quickstart.md` — step-by-step quickstart
- `docs/guide/specs.md` — authoring function specs
- `docs/guide/config.md` — configuration reference
- `docs/guide/cli.md` — CLI usage
- `docs/guide/runtime.md` — runtime, sessions, cache, sandbox
- `docs/guide/context-docs.md` — context docs and docgen
- `docs/guide/dependencies.md` — dependency policy and session envs
- `docs/guide/errors.md` — exceptions and troubleshooting

## Development
Run tests and linters:

```bash
pytest -q
ruff check .
mypy splice
```

