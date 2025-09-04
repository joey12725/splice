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

### Caching
Generated code is cached per `(session_id, function_name, prompt_hash, spec_hash, context_hash, config_hash)` in `.splice/db.sqlite`.

### Sandbox
Execution runs in a child process with restricted builtins and import allowlist. Filesystem, network, and subprocess access are gated by config.

Tune via `sandbox` section in config.


