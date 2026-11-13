# Changelog

## 0.2.0 (2026-11-13)

The sandbox is rebuilt from the ground up. Generated code no longer runs in a
fork of your process; it runs in a fresh interpreter behind a pluggable,
OS-level sandbox.

### Added

- `splice.sandbox`: a `Sandbox` interface, a backend registry
  (`register_backend`) and five backends: `process`, `seatbelt` (macOS),
  `bubblewrap` (Linux), `docker` and `podman`. `sandbox.backend: auto` picks
  the strongest local one.
- Resource limits: wall clock, CPU time, memory, file size, open files and
  output size, configurable under `sandbox:`.
- Environment scrubbing with explicit `sandbox.env_passthrough`.
- CPython audit-hook policy inside the sandbox (filesystem, network, process,
  ctypes, gc and frame access).
- `Executor.execute()` returning an `ExecutionResult` with captured
  stdout/stderr, duration and backend name.
- `Splice(client=..., sandbox=...)` for injecting a code generator or backend.
- `splice sandbox` command.
- New exceptions: `ResourceLimitExceeded`, `ExecutionTimeout`,
  `SerializationError`, `SandboxUnavailableError`, `PromptRequiredError`.
- Offline examples (`examples/quickstart.py`, `examples/calculator_demo.py
  --offline`) and an escape-test suite that runs against every available
  backend.
- CI on Linux (Python 3.10 to 3.13, process + bubblewrap), macOS (seatbelt)
  and Docker.

### Changed (breaking)

- **Python 3.10+** is required (was 3.9).
- **Arguments and return values must be plain data.** They cross the sandbox
  boundary as tagged JSON: numbers, strings, bytes, lists, tuples, dicts, sets,
  dates, `Decimal`, `Fraction`, `UUID` and numpy arrays. Arbitrary objects
  raise `SerializationError`. Previously the forked child received objects by
  memory and returned them by pickle, which let generated code run arbitrary
  code in the parent during unpickling.
- **`allow_fs: true` now means a private scratch directory**, not the host
  filesystem. Host paths stay unreadable regardless of the setting.
- **The language guard is stricter.** Dunder attribute access (other than
  `__name__`, `__doc__`, `__qualname__`, `__module__`, `__init__`), `getattr`,
  `globals`, `vars`, frame attributes and relative imports are rejected, and
  allowed modules are exposed as views that refuse to hand out non-allowlisted
  submodules.
- **`Executor.run(timeout_seconds=None)`** now means "use
  `sandbox.timeout_seconds` from config" (default 10 s) instead of "no
  timeout".
- **Timeouts raise `ExecutionTimeout`** and limit breaches raise
  `ResourceLimitExceeded`. Both subclass `ExecutionError`, so existing
  `except ExecutionError` handlers still work.
- **A missing prompt raises `PromptRequiredError`** (a `SpliceError` and a
  `ValueError`, so existing `except ValueError` handlers still work).
- **The repair loop only retries Splice errors** (`ExecutionError`,
  `SandboxViolation`, `ValidationError`), not `KeyboardInterrupt` and friends.
- **4xx responses from OpenRouter fail fast** instead of being retried; 408,
  429 and 5xx are still retried.
- The `splice-demo-calculator` console script is removed; run
  `python examples/calculator_demo.py` instead.

### Fixed

- The default `logging.database: .splice/db.sqlite` was resolved relative to
  `.splice/`, creating `.splice/.splice/db.sqlite`. It is now relative to the
  project root.
- `splice init` and `docgen` outside an existing workspace created `.splice/`
  in the current directory instead of the requested path.
- `SpliceConfig.load()` with no workspace raised instead of returning defaults.
- Spec edits were ignored for the life of the process because specs were
  memoised.
- Validation error messages named the wrong parameter (late-binding closure).
- Pydantic v2 models are supported (`model_validate`), alongside v1.

## 0.0.1 (2025-09-04)

Initial version: YAML specs, deterministic prompt bundling, OpenRouter client,
per-session SQLite cache, repair loop, dependency policy, docgen and CLI.
