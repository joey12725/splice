# Phase 5 — Session manager + SQLite cache

Phase 5 introduces a SQLite-backed artifact store under `.splice/db.sqlite` that caches generated code per `(session_id, func_name, prompt_hash, spec_hash, context_hash, config_hash)`. The `Splice.run` API now provides the end-to-end flow: load spec/config, assemble prompt, generate code on first call, cache it, execute in the sandbox, and return the value.

## What it builds
- `splice.store.ArtifactStore`: manages sessions, artifacts, and lightweight events.
- `Splice.run(...)`: uses the store to reuse previously generated code for the same session+inputs.

## Cache keys
- `session_id`: opaque string from `Session.ensure()`.
- `func_name`: spec name.
- `prompt_hash`: SHA-256 of the active prompt (call-time or spec default).
- `spec_hash`: SHA-256 of the spec YAML text.
- `context_hash`: SHA-256 of merged context docs content.
- `config_hash`: SHA-256 of the config YAML text.

## TTL and GC
- TTL is configured via `sessions.ttl` (e.g., `24h`, `60m`, `30s`).
- A best-effort purge runs on each `run()` call to remove `artifacts.last_used_ts < now - TTL`.

## Usage
```python
from splice import Splice, Session

splice = Splice()
sess = Session.ensure()

# First call requires a prompt
result = splice.run("generic_operand", session=sess, prompt="Return max(a, b)", a=3.0, b=5.0)

# Subsequent calls in the same session skip generation
result = splice.run("generic_operand", session=sess, a=4.0, b=2.0)
```

## Tests
- See `tests/test_phase5_cache.py` for cache hit/TTL purge behavior.


