# Phase 8 — Minimal CLI

Phase 8 adds a tiny CLI surface to scaffold a project, generate docs, and purge the cache. Commands are designed to be safe and operate only within `.splice/`.

## Commands
- `splice init` — create `.splice/`, `functions/`, `context/`, and a default `splice.yaml` if missing.
- `splice docgen --types User Asset pandas.DataFrame` — write docs to `.splice/context/*.md` for given import paths.
- `splice cache purge` — clear all cached artifacts in the SQLite database.

## Programmatic API
```python
from splice.cli import cmd_init, cmd_docgen, cmd_cache_purge

base = cmd_init()
cmd_docgen(["pandas.DataFrame"])  # generates .splice/context/DataFrame.md
cmd_cache_purge()                 # empties the artifacts table
```

## Tests
- See `tests/test_phase8_cli.py` for scaffolding, docgen, and purge behavior.


