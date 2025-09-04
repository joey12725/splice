## Function Specs

Function specs declare what the LLM should generate and how to run it.

Location: `.splice/functions/<name>.yaml`

### Required fields
- `name` — spec name (must match filename)
- `version` — semver
- `description` — human-readable description
- `prompt` — default session-scoped prompt text
- `contracts.signature` — exact Python signature
- `contracts.inputs` — map of name -> type (string)
- `contracts.output` — return type (string)

### Optional fields
- `system_prompt` — overrides global model system prompt
- `contracts.pydantic` — param/output validators (import paths)
- `context_docs` — names of `.splice/context/*.md` docs to include
- `type_sources` — introspection sources for docgen
- `examples` — few-shot `{ prompt, function }` pairs

### Example
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

### Tips
- Keep signatures stable; cache keys include the spec hash.
- Prefer concrete types; add Pydantic models for complex shapes.
- Add `examples` for tricky behaviors; they are bundled deterministically.


