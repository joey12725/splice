# Errors and troubleshooting

Every exception derives from `splice.SpliceError`.

| Exception | Raised when |
| --- | --- |
| `ConfigError` | `splice.yaml` is invalid |
| `SpecNotFoundError` / `SpecError` | a function spec is missing or malformed |
| `PromptRequiredError` | no cached code exists and no `prompt=` was given (also a `ValueError`) |
| `GenerationError` | the model call failed or returned no code |
| `SandboxViolation` | generated code tried something the policy forbids |
| `ExecutionError` | the function raised, or the sandbox failed |
| `ResourceLimitExceeded` | CPU, memory, file-size or output limit hit (subclass of `ExecutionError`) |
| `ExecutionTimeout` | wall-clock limit hit (subclass of `ResourceLimitExceeded`) |
| `SerializationError` | an argument or return value cannot cross the sandbox boundary |
| `SandboxUnavailableError` | the configured backend cannot run on this machine |
| `ValidationError` | inputs or outputs do not match the contract |
| `DependenciesError` | a required package is missing or failed to install |
| `WorkspaceNotFoundError` | no `.splice/` directory; run `splice init` |

## Common fixes

- **Missing API key:** set `OPENROUTER_API_KEY`, or pass your own generator
  with `Splice(client=...)`.
- **Import blocked:** add the module to `sandbox.allow_imports`. Filesystem,
  network and process modules also need the matching `allow_*` switch.
- **`SerializationError`:** pass and return plain data (numbers, strings,
  lists, dicts, tuples, sets, bytes, dates, Decimals, numpy arrays).
- **`SandboxUnavailableError`:** run `splice sandbox` to see what this machine
  supports, or set `sandbox.backend: auto`.
- **Stale behaviour while iterating:** `splice cache purge`.
