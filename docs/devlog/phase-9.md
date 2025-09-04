# Phase 9 — Examples ingestion + verification

Phase 9 enables using examples in specs while performing a lightweight verification at load time to catch obvious mismatches.

## What it builds
- Spec loader now validates that each example's function text references the same function name as in `contracts.signature`.
- This prevents confusing prompts where the example function name doesn't match the declared signature.

## Behavior
- The check is best-effort and only enforces the function name. It does not parse arguments or types.
- On mismatch, a `SpecError` is raised.

## Tests
- See `tests/test_phase9_examples.py` for bad-name flagging and good-name acceptance.


