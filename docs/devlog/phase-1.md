# Phase 1 — Config and Spec Loader (YAML-first)

Phase 1 introduces YAML loaders for the global config (`.splice/splice.yaml`) and function specs (`.splice/functions/*.yaml`) with schema validation and typed objects.

## Global Config — `.splice/splice.yaml`

### Purpose
Define model/runtime defaults once per project.

### Defaults
- `model`: `name=openai/gpt-5-mini`, `temperature=0.2`, `reasoning=1`, `system_prompt` instructs the model to output exactly one Python function matching the signature.
- `sessions`: `store=sqlite`, `ttl=24h`.
- `logging`: `database=.splice/db.sqlite`, `log_inputs=false`, `log_outputs=false`.
- `sandbox`: `allow_imports=["math", "statistics", "numpy"]`, `allow_fs=false`, `allow_net=false`, `allow_subprocess=false`.
- `dependencies`: `policy=if-present` (`off | if-present | allow`).
- `retries`: `generation=2`, `repair=1`.

### Example
```yaml
model:
  name: openai/gpt-5-mini
  temperature: 0.2
  reasoning: 1
  system_prompt: |
    You are a code generator. Output exactly one valid Python function that
    matches the declared signature and contracts. No explanations.

sessions:
  store: sqlite   # memory | sqlite | redis
  ttl: 24h

logging:
  database: .splice/db.sqlite
  log_inputs: false
  log_outputs: false

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

### Loading and resolution
- Programmatic loader: `SpliceConfig.load(config_path: str | None = None, start_path: Path | None = None)`
  - If `config_path` provided, load it.
  - Else locate nearest `.splice/` via `find_splice_directory(start_path)` and read `splice.yaml`.
  - If the file is missing, return defaults.

```python
from splice.config import SpliceConfig
cfg = SpliceConfig.load()  # applies defaults & validation
print(cfg.model.name)
```

### Validation rules
- `sessions.store`: one of `memory | sqlite | redis`.
- `sandbox.allow_imports`: list of strings.
- `dependencies.policy`: one of `off | if-present | allow`.
- Numeric and boolean fields are coerced to expected types; invalid shapes raise `ConfigError`.

## Function Specs — `.splice/functions/*.yaml`

### Purpose
Describe an LLM-generated function’s contract and context.

### Required fields
- `name` (string) — must match the filename (e.g., `generic_operand.yaml`).
- `version` (semver string)
- `description` (string)
- `prompt` (string) — default session-scoped prompt text.
- `contracts`:
  - `signature` (string) — exact Python signature to implement.
  - `inputs` (map of `str -> str`) — param name to Python type.
  - `output` (string) — return type.

### Optional fields
- `system_prompt` (string) — function-level override of the global system prompt.
- `pydantic` (map of `str -> import path`) — optional Pydantic models for inputs/output.
- `context_docs` (list of strings) — names of doc files to include.
- `type_sources` (list of objects) — how to generate context docs (`name`, `import`, `doc_strategy`).
- `examples` (list) — few-shot `{ prompt, function }` pairs.

### Minimal example
```yaml
name: generic_operand
version: 0.1.0
description: Binary numeric operation from a natural-language prompt
prompt: Describe the operation using 'a' and 'b'.
contracts:
  signature: "def generic_operand(a: float, b: float) -> float"
  inputs:
    a: float
    b: float
  output: float
context_docs: []
type_sources: []
examples: []
```

### Loading a spec
- `splice.spec(name)` returns a typed `FunctionSpec` by loading `.splice/functions/<name>.yaml`.
- Direct loader: `load_function_spec(name)`.

```python
from splice import Splice
splice = Splice()
spec = splice.spec("generic_operand")
print(spec.contracts.signature)
```

### Validation rules
- `name` in YAML must equal the filename.
- `contracts.inputs`: dict of `str -> str`.
- `system_prompt` if present must be a string.
- `context_docs`, `type_sources`, `examples` must be lists; invalid shapes raise `SpecError`.

## Notes and next steps
- Prompt scope: prompts are session-scoped and provided on the first call per `(session, func_name)` — enforced in later phases.
- Generation, sandboxed execution, caching, validation, and docgen arrive in Phases 2–7.
- For now, Phase 0–1 provide: config/spec typing, loading, and validation only.
