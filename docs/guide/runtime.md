## Runtime, Sessions, Cache, Sandbox

### Sessions
Use `Session.ensure()` to create/reuse an opaque session id. Cache and dependency envs are scoped by session.

```python
from splice import Session
sess = Session.ensure()
```

### Running functions
```python
from splice import Splice

result = Splice().run(
  "generic_operand",
  session=sess,
  prompt="Return max(a, b)",
  a=3.0,
  b=5.0,
)
```

Generate-only mode (no execution) using `run_now=False`:
```python
from splice import Splice

# Generates and caches code using the provided prompt, returns None
Splice().run("generic_operand", session=sess, prompt="Return max(a, b)", run_now=False)

# Later, execute normally; if the generated code fails on this first actual run,
# Splice will still attempt a repair using the error and retry once (per config).
val = Splice().run("generic_operand", session=sess, a=3.0, b=5.0)
```

### Caching
Generated code is cached per `(session_id, function_name, prompt_hash, spec_hash, context_hash, config_hash)` in `.splice/db.sqlite`.

### Sandbox
Execution runs in a child process with restricted builtins and import allowlist. Filesystem, network, and subprocess access are gated by config.

Tune via `sandbox` section in config.


