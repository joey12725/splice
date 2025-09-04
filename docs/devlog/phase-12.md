# Phase 12 — Logging & lightweight observability

Extends the SQLite events table to include generation and execution events with durations.

## Events
- `generation_requested`
- `generation_succeeded` (duration_ms)
- `execution_succeeded` (duration_ms)
- `execution_failed` (error summary)

## API
Use `ArtifactStore.list_events()` to read events for inspections/tests.

## Tests
- See `tests/test_phase12_logging.py`.


