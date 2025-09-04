# Phase 6 — Contracts (Python/Pydantic) validation

Phase 6 adds input and output validation around the executor using the contracts declared in each function spec. Validation ensures bad inputs are caught before execution and outputs match expected types.

## What it builds
- `splice.validation.build_validators(spec)` creates:
  - per-parameter validators based on either Pydantic models (if provided) or simple `isinstance` checks for known types.
  - an output validator using the same rules.
- `Splice.run` wraps execution with pre/post validation.

## Behavior
- If a Pydantic model is specified (via `contracts.pydantic.<param>` or `contracts.pydantic.output`), it is used for validation.
- Otherwise, a best-effort type check is performed for common builtins or imported types (resolved via import path). If a type can't be resolved, validation degrades gracefully.
- Validation failures raise `ValidationError`.

## Example
```yaml
contracts:
  signature: "def generic_operand(a: float, b: float) -> float"
  inputs:
    a: "float"
    b: "float"
  output: "float"
```

```python
from splice import Splice, Session

res = Splice().run("generic_operand", session=Session.ensure(), prompt="Return max(a, b)", a=1.0, b=2.0)
```

## Tests
- See `tests/test_phase6_validation.py` for input and output validation cases.


