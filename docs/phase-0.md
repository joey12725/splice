# Phase 0 — Project bootstrap

Phase 0 establishes a clean, minimal package you can install and import without side effects, with CI, tests, and a `.splice/` folder convention.

## What you get
- A Python package `splice` exposing `Splice` and `Session`.
- Editable install with dev tooling (ruff, mypy, pytest).
- Minimal CI workflow (lint, type-check, tests).
- `.splice/` folder convention and a path resolver.

## Repository layout
```
splice/
  pyproject.toml
  README.md
  splice/
    __init__.py
    core.py          # Splice, Session (no side-effects)
    paths.py         # find_splice_directory()
    errors.py        # base exceptions
  tests/
    test_import.py
    test_config_and_specs.py   # Phase 1 tests (ignored here)
  .github/workflows/ci.yml
```

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Public API (so far)
```python
from splice import Splice, Session

splice = Splice()             # no side effects
sess = Session.ensure()       # returns a new opaque session id
```

- `Session.ensure(existing=None) -> Session`: returns existing or new session with a UUID.
- `Splice(config_path: str | None = None)`: records a config path for later use; no loading yet.

## `.splice/` convention and path resolver
- Convention: project-local metadata under `.splice/` (created by you or later by CLI).
- Resolver: `splice.paths.find_splice_directory(start_path: Path | None) -> Path` walks up from `start_path` (or CWD) to find the nearest `.splice/` directory; falls back to `CWD/.splice` if none exists.

Example:
```python
from pathlib import Path
from splice.paths import find_splice_directory

root = find_splice_directory(Path.cwd())
print(root)  # /path/to/your/project/.splice
```

## CI
- GitHub Actions workflow runs on push/PR to `main`:
  - Lint: `ruff check .`
  - Type-check: `mypy splice`
  - Tests: `pytest -q`

## Exit criteria
- `pip install -e .` works.
- `from splice import Splice, Session` imports without side effects.
- CI passes (lint, type-check, tests) locally and in GitHub Actions.
