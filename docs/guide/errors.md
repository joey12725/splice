## Errors & Troubleshooting

### Exceptions
- `ConfigError` — invalid `.splice/splice.yaml`
- `SpecNotFoundError` / `SpecError` — missing/invalid function spec
- `GenerationError` — model call failed or returned invalid content
- `SandboxViolation` — disallowed import or operation in the sandbox
- `ExecutionError` — runtime failure, timeout, or signature mismatch
- `ValidationError` — inputs/outputs don't satisfy contracts
- `DependenciesError` — missing or failed dependency installation
- `WorkspaceNotFoundError` — `.splice/` workspace not found (run `splice init`)

### Common issues
- Missing API key: set `OPENROUTER_API_KEY` in your environment.
- Spec not found: ensure `.splice/functions/<name>.yaml` exists.
- Sandbox import blocked: add the module to `sandbox.allow_imports`.
- Cache confusion: use `splice cache purge` during development.


