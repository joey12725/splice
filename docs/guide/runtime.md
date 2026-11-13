# Runtime, sessions and caching

## Sessions

`Session.ensure()` returns a new opaque session (or the one you pass in).
Generated code, prompts and per-session dependency environments are scoped to
it, so two users can define the same function differently.

```python
from splice import Session, Splice

alice, bob = Session.ensure(), Session.ensure()
sp = Splice()
sp.run("blend", session=alice, prompt="Return the average of a and b", a=1.0, b=3.0)  # 2.0
sp.run("blend", session=bob, prompt="Return a to the power of b", a=2.0, b=3.0)       # 8.0
```

## A call, step by step

1. Locate `.splice/`, load `splice.yaml` and the function spec.
2. Build the cache key from the session, function name and hashes of the
   prompt, spec, context docs and config.
3. On a miss, bundle the prompt and ask the code generator for a function.
4. Validate the arguments against the contract.
5. Prepare dependencies per `dependencies.policy`.
6. Execute in the sandbox backend.
7. Validate the return value.
8. On an execution error, sandbox violation or bad return value, send the
   error back to the model and retry, up to `retries.repair` times.

## Caching

See [architecture](../architecture.md#caching) for the key design. Useful knobs:

- `sessions.ttl`: how long artifacts live (`30m`, `24h`, `7d`).
- `splice cache purge`: drop every cached artifact.
- `run_now=False`: generate and cache without executing.

## Sandbox

Generated code always runs out of process, in a fresh interpreter, behind the
backend selected by `sandbox.backend`. See [security](../security.md).

To look at what ran, use `Executor.execute`, which returns the value plus
captured stdout/stderr, duration and backend name:

```python
from splice import Executor, SpliceConfig

result = Executor.execute(code, "def f(x: int) -> int", {"x": 1}, SpliceConfig())
print(result.value, result.stdout, result.duration_ms, result.backend)
```
