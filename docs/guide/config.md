# Configuration

Workspace config lives at `.splice/splice.yaml`. Every key is optional;
missing keys take the defaults shown here.

```yaml
model:
  name: openai/gpt-5-mini      # any OpenRouter model id
  temperature: 0.2
  reasoning: 1                 # 0-3 or minimal | low | medium | high
  system_prompt: |
    You are a code generator. Output exactly one valid Python function that
    matches the declared signature and contracts. No explanations.

sessions:
  store: sqlite
  ttl: 24h                     # 500ms, 30s, 15m, 24h, 7d

logging:
  database: .splice/db.sqlite  # relative to the project root

sandbox:
  backend: auto                # auto | process | seatbelt | bubblewrap | docker | podman
  allow_imports: ["math", "statistics", "numpy"]
  allow_fs: false              # read/write a private scratch dir (never the host fs)
  allow_net: false
  allow_subprocess: false
  restricted_python: true      # language guard; the process and OS layers apply either way
  timeout_seconds: 10          # wall clock
  cpu_seconds: 10
  memory_mb: 512
  max_file_size_mb: 16
  max_open_files: 64
  max_output_kb: 1024          # captured stdout/stderr and the encoded result
  env_passthrough: []          # env var names to expose; nothing is inherited otherwise
  python: null                 # interpreter for local backends (default: the current one)
  container_image: python:3.12-slim

dependencies:
  policy: if-present           # off | if-present | allow

retries:
  generation: 2                # transport/5xx/429 retries per model call
  repair: 1                    # model repair rounds after a failed execution
```

## Sandbox keys

| Key | Effect |
| --- | --- |
| `backend` | Which isolation backend runs the code. `auto` picks seatbelt on macOS, bubblewrap on Linux when usable, otherwise `process`. Containers are opt-in. |
| `allow_imports` | Top-level modules generated code may import. Submodules are reachable only if their root is listed. |
| `allow_fs` | Grants read/write inside a per-call scratch directory. Host paths stay unreadable. |
| `allow_net` | Allows sockets and DNS. The kernel profiles open up to match. |
| `allow_subprocess` | Allows `fork`/`exec`. The process-count limit is lifted. |
| `restricted_python` | Turns the AST/builtins guard on or off. |
| `timeout_seconds`, `cpu_seconds`, `memory_mb`, `max_file_size_mb`, `max_open_files`, `max_output_kb` | Hard limits; breaching one raises `ResourceLimitExceeded` or `ExecutionTimeout`. |
| `env_passthrough` | Copies the named variables from your environment into the sandbox. |
| `python` | Interpreter for local backends. Third-party modules in `allow_imports` must be installed for it. |
| `container_image` | Image for `docker`/`podman`. It needs Python 3.10+ and any third-party modules you allow. |

Changing any of these changes the config hash, so cached code is regenerated
under the new policy.

## Programmatic access

```python
from splice import SpliceConfig

cfg = SpliceConfig.load()             # nearest .splice/splice.yaml, or defaults
cfg = SpliceConfig.from_dict({"sandbox": {"backend": "docker", "memory_mb": 256}})
```

## Editing from the CLI

```bash
splice edit --set-model openai/gpt-5-mini --set-reasoning high
splice edit --set-system-prompt-file ./system.txt
splice edit --set-sandbox-imports math,statistics,numpy --disable-net --disable-fs
splice edit --set-deps-policy allow --set-retries-generation 3 --set-retries-repair 2
```
