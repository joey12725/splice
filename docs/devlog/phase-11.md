# Phase 11 — Dependency policy: if-present + allow

Adds a minimal dependency resolver used ahead of execution.

## Policies
- `off`: do nothing.
- `if-present`: require dependencies to already be installed; fail fast otherwise.
- `allow`: attempt to install missing packages using `pip`.

## API
```python
from splice.deps import DependencyPolicy

DependencyPolicy(policy="if-present").ensure(["numpy"])  # raises if missing
DependencyPolicy(policy="allow").ensure(["pandas"])     # installs if missing
```

## Tests
- See `tests/test_phase11_deps.py`.


