# Dependencies & Session Envs

Splice can optionally ensure/import dependencies before executing generated code.

## Policy
- `off`: do nothing
- `if-present`: require packages to be already installed; fail fast otherwise
- `allow`: install missing packages into a per-session virtualenv under `.splice/cache/venv/<session>`

## Programmatic API
```python
from splice.deps import DependencyPolicy

DependencyPolicy(policy="if-present").ensure(["numpy"])  # raises if missing
```

When `allow` is enabled, Splice prepares a session env and installs packages
with `pip`, in your process, before the call. The env's `site-packages` is then
mounted into the sandbox as a read-only import root. Generated code never runs
`pip` itself.


