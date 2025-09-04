# Phase 14 — Performance pass

Adds an LRU cache on spec loading and a perf test to ensure cached executions are faster than initial generation.

## Notes
- `@lru_cache` added to `load_function_spec`.
- Cached execution should be significantly faster in a tight loop.

## Tests
- See `tests/test_phase14_perf.py`.


