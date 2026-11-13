# Extending Splice

## Bring your own model

`Splice` accepts any object with a `generate_code(bundle, config) -> str`
method. The bundle's `.text` is the full prompt; return Python source.

```python
from splice import PromptBundle, Session, Splice, SpliceConfig


class AnthropicGenerator:
    def __init__(self, client, model: str) -> None:
        self.client, self.model = client, model

    def generate_code(self, bundle: PromptBundle, config: SpliceConfig) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": bundle.text}],
        )
        text = msg.content[0].text
        return text.split("```python")[-1].split("```")[0].strip()


sp = Splice(client=AnthropicGenerator(client, "your-model-id"))
```

The same hook makes tests deterministic: `examples/offline.py` and
`tests/test_runtime.py` use scripted generators and never touch the network.

## Bring your own sandbox

Subclass `splice.Sandbox`, implement `execute`, and register it:

```python
from splice import Sandbox, register_backend
from splice.sandbox import ExecutionRequest, ExecutionResult, SandboxPolicy


class RemoteRunner(Sandbox):
    name = "remote"
    isolation = "Firecracker microVM on the build farm"

    @classmethod
    def is_available(cls) -> bool:
        return True

    def execute(self, request: ExecutionRequest, policy: SandboxPolicy) -> ExecutionResult:
        payload = {
            "code": request.code,
            "function": request.function_name,
            "kwargs": dict(request.kwargs),
            "limits": vars(policy.limits),
        }
        value = post_to_runner(payload)  # your transport
        return ExecutionResult(value=value, backend=self.name)


register_backend("remote", RemoteRunner)
```

Then select it in `splice.yaml`:

```yaml
sandbox:
  backend: remote
```

or pass an instance directly: `Splice(sandbox=RemoteRunner())`.

Raise `splice.SandboxViolation` for policy denials,
`splice.ExecutionTimeout` / `splice.ResourceLimitExceeded` for limits and
`splice.ExecutionError` for everything else, so the repair loop and callers
see consistent errors.

### Reusing the runner

If your backend can start a Python process, reuse the existing runner instead
of writing your own protocol. Subclass `ProcessSandbox` and override
`wrap_command` to prefix the command with your isolation tool; the request
encoding, limits, audit hook, output capture and error mapping all come for
free. `SeatbeltSandbox` and `BubblewrapSandbox` are about 60 lines each this
way.

```python
from splice.sandbox import ProcessSandbox, SandboxPolicy


class FirejailSandbox(ProcessSandbox):
    name = "firejail"
    isolation = "process sandbox + firejail profile"

    def wrap_command(self, command, *, workdir, policy: SandboxPolicy, python):
        net = [] if policy.allow_net else ["--net=none"]
        return ["firejail", "--quiet", "--private=" + workdir, *net, *command]
```

## Values across the boundary

Arguments and return values travel as tagged JSON. Supported types: `None`,
`bool`, `int`, `float` (including `nan`/`inf`), `str`, `bytes`, `bytearray`,
`list`, `tuple`, `dict` (any hashable keys), `set`, `frozenset`, `complex`,
`Decimal`, `Fraction`, `datetime`/`date`/`time`/`timedelta`, `UUID`, and numpy
arrays and scalars. Anything else raises `SerializationError`; convert rich
objects to plain data at the edge of the call.
