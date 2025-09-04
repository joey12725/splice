# Phase 10 — Error handling + auto-repair

Adds an execution-time repair loop. When the generated function raises during execution, Splice asks the model for a fixed function using the same bundle plus minimal error context, up to `retries.repair` attempts.

## Behavior
- On first execution failure, log `execution_failed` and request a new function.
- On success, log `execution_succeeded` with duration.
- Generation events include `generation_requested` and `generation_succeeded` with durations.

## Configuration
- `retries.repair`: number of repair attempts (default 1 → two total tries).

## Tests
- See `tests/test_phase10_repair.py` for a two-attempt repair scenario.


