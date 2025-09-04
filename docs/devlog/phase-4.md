## Phase 4 — Sandboxed executor (unsafe mutation MVP)

This phase introduces a child-process executor that runs generated code with restricted builtins and an import allowlist from config. Filesystem, network, and subprocess access are gated by flags.

### Capabilities

- Executes a single function from generated code in an isolated process.
- Enforces:
  - Import allowlist: `config.sandbox.allow_imports` (default: ["math", "statistics", "numpy"]).
  - Restricted builtins (no `__import__`, `eval`, `exec`, `open` unless `allow_fs=true`).
  - AST preflight checks for disallowed imports and dangerous names.
  - Signature shape check: name and parameter order must match `contracts.signature`.
  - Timeout (default 10s) to kill runaway executions.

### Public API

```python
from splice import Executor, SpliceConfig

cfg = SpliceConfig()  # loads defaults or .splice/splice.yaml if present
code = """
def add(a: int, b: int) -> int:
    return a + b
"""
result = Executor.run(code, "def add(a: int, b: int) -> int:", {"a": 2, "b": 3}, cfg)
assert result == 5
```

Raises `SandboxViolation` for disallowed operations and `ExecutionError` for runtime/signature/timeouts.

### Configuration

From `notes/requirements.md` and `notes/timeline.md`:

- Global config at `.splice/splice.yaml` controls sandbox behavior under the `sandbox` section:

```yaml
sandbox:
  allow_imports: ["math", "statistics", "numpy"]
  allow_fs: false
  allow_net: false
  allow_subprocess: false
```

### Tests

- Unit tests: `tests/test_executor.py`
  - basic function execution
  - disallowed import blocked
  - numpy allowed if present
  - filesystem gate respected
  - timeout handling
  - signature mismatch detection

- Live API tests updated: `tests/test_live_api.py`
  - Execute model-generated code via the sandbox
  - Gated by `OPENROUTER_API_KEY` and `SPLICE_RUN_LIVE_TESTS=1`

### Notes

This is an MVP sandbox. Later phases will harden via tighter AST checks, safer import hooks, and OS-level limits.


