# Splice — Development Timeline (phased, in order)

Below is a pragmatic build sequence. Each phase lists **what to build**, **why it comes now**, and crisp **exit criteria** so you can ship value incrementally without blocking on later features.

---

## Phase 0 — Project bootstrap

**Build**

* Monorepo layout (or single repo) with `splice/` package, tests, and examples.
* Packaging (pyproject + wheels), basic CI (lint, type-check, tests).
* `.splice/` folder convention and path resolver.

**Exit criteria**

* `pip install -e .` works.
* Import `from splice import Splice, Session` without side effects.

---

## Phase 1 — Config + Spec loader (YAML-first)

**Build**

* `splice.yaml` loader with defaults you set (model.name, temperature, reasoning, system\_prompt; sessions/logging/sandbox/deps/retries).
* Function spec loader for `.splice/functions/*.yaml` with schema validation:

  * `name`, `version`, `description`, `prompt` (per-session), `system_prompt`,
  * `contracts` (signature, inputs, output, optional pydantic map),
  * `context_docs`, `type_sources`, `examples` (prompt/function pairs).

**Exit criteria**

* Invalid specs/configs fail fast with human-readable errors.
* `splice.spec("generic_simulation_hook")` returns a typed object.

---

## Phase 2 — Prompt bundler

**Build**

* Deterministic assembly of the model prompt from:

  * global `system_prompt` (from config) overridden by spec-level `system_prompt`,
  * spec `contracts.signature`,
  * `contracts` types (for clarity),
  * `context_docs` (loaded from `.splice/context/*.md`),
  * **session-scoped prompt** (call-time or spec default),
  * `examples` (prompt/function pairs).
* Strict “return **one** Python function, no prose” instruction.

**Exit criteria**

* Given a spec + prompt, `bundle = Prompt(spec, session_prompt, docs, examples)` produces a text blob ready for the model.

---

## Phase 3 — OpenRouter client

**Build**

* Minimal HTTP client with:

  * model `name`, `temperature`, `reasoning` passthrough,
  * token/size guardrails (truncate docs when needed),
  * retries per config,
  * code-block extraction (triple-backtick parsing).
* Redaction of sensitive values if `log_inputs/outputs=false`.

**Exit criteria**

* `client.generate_code(bundle)` returns a clean Python function string or a structured failure.

---

## Phase 4 — Sandboxed executor (unsafe mutation MVP)

**Build**

* Child-process runner:

  * filtered builtins, import allowlist from config,
  * `allow_fs`, `allow_net`, `allow_subprocess` gates,
  * dependency policy `off | if-present | allow` (but **install** comes later).
* Loader that:

  * compiles the generated code,
  * locates the exact function name from `contracts.signature`,
  * checks signature shape (count/names/annotations) before activation.

**Exit criteria**

* `Executor.run(func_code, call_args)` executes and returns the value.
* Disallowed imports/ops throw controlled errors.

---

## Phase 5 — Session manager + SQLite cache

**Build**

* SQLite store in `.splice/db.sqlite` for:

  * session table,
  * function artifacts (code, metadata, hashes),
  * logs/events (basic).
* Cache keys: `(session_id, func_name, prompt_hash, spec_hash, context_hash, config_hash)`.
* TTL + GC task that purges expired artifacts.

**Exit criteria**

* First call compiles & caches; subsequent calls in same session skip model call.
* Purge removes old artifacts and shrinks DB.

---

## Phase 6 — Contracts (Python/Pydantic)

**Build**

* Parse `contracts.signature`, `contracts.inputs`, `contracts.output`.
* Dynamic import of types; optional Pydantic model binding.
* Input/output validation around executor calls (pre/post).

**Exit criteria**

* Wrong input types raise clear exceptions before execution.
* Output validated against declared type/model.

---

## Phase 7 — Context docs (DocGen)

**Build**

* `docgen` engine using `type_sources`:

  * class/instance introspection (attrs, methods, signatures, docstrings, type hints),
  * reference-following when obvious (e.g., doc `User` mentions `Asset`).
* Write to `.splice/context/<Type>.md`. Idempotent updates.

**Exit criteria**

* Running docgen once makes reproducible context files for builtins/third-party/custom types.
* Manual edits are preserved on subsequent runs unless forced.

---

## Phase 8 — Minimal CLI

**Build**

* `splice init` — scaffold `.splice/` + default `splice.yaml`.
* `splice docgen --types User Asset Loan pandas.DataFrame` — generate context docs.
* `splice make-func <name> --auto | --minimal`

  * `--auto`: scan nearby code (simple regex window) + LLM to prefill spec fields (`description`, `contracts.signature`, types) and seed example pairs.
  * `--minimal`: bare skeleton only.
* `splice cache purge` — clear artifacts + wipe SQLite safely.

**Exit criteria**

* Commands run with helpful output; no side effects outside `.splice/`.

---

## Phase 9 — Examples ingestion + prompt/function verification

**Build**

* Include examples (few-shot) in the bundle.
* Optional **verification path**: run each example function (from spec) in the sandbox to ensure signature compliance (no external deps).

**Exit criteria**

* Bad example functions (wrong signature) are flagged at load time.
* Bundle includes example pairs that the model can see.

---

## Phase 10 — Error handling + auto-repair

**Build**

* Generation retry policy (config).
* Runtime repair loop:

  * capture exception + minimal traceback,
  * send back with the **same** prompt bundle to request a fixed function,
  * limited attempts per config.

**Exit criteria**

* Demonstrable self-heal on simple defects (e.g., NameError, attribute typo).
* Clear final error if repair budget exhausted.

---

## Phase 11 — Dependency policy: `if-present` + `allow`

**Build**

* `if-present`: allowed imports if installed; otherwise fail gracefully.
* `allow`: ephemeral per-session venv with `pip install` (wheel cache under `.splice/cache/`), isolated from system Python.

**Exit criteria**

* A spec that needs `numpy` runs under both policies accordingly.
* Cache avoids re-installing the same version repeatedly.

---

## Phase 12 — Logging & lightweight observability

**Build**

* Event tables in SQLite:

  * `generation_requested/succeeded/failed`,
  * `execution_succeeded/failed` (+ duration),
  * token/cost if available.
* Toggle payload logging via config.

**Exit criteria**

* You can query DB to answer: “Which sessions used what code and did it error?”

---

## Phase 13 — Integration samples

**Build**

* **Monte Carlo demo**: `generic_simulation_hook` wired into a tight loop; two scenarios with different prompts.
* **Tiny calc demo**: `generic_operand` with a textbox prompt.

**Exit criteria**

* Both samples run locally and prove “one LLM call → thousands of executions” with unsafe mutation.

---

## Phase 14 — Performance pass

**Build**

* Micro-benchmarks for executor overhead and validation overhead.
* Hot path profiling; simple caching of imported types, signature parsing, and compiled function objects.

**Exit criteria**

* Inner-loop overhead small enough for per-timestep simulation.
* No material memory leaks across many sessions.

---

## Phase 15 — Docs & packaging

**Build**

* README + “Spec reference” (fields, examples).
* “How session prompts work” doc.
* Quickstart for Monte Carlo + calc demos.
* Versioned changelog; semantic versioning.

**Exit criteria**

* `pip` package installs cleanly; docs make a newcomer productive quickly.

---

## Phase 16 — Hardening & guardrails (optional before public)

**Build**

* AST preflight checks (ban `exec`, `eval`, `__import__`, etc. unless whitelisted).
* Safer import hook to enforce allowlist.
* Timeouts and memory limits at process level where possible.

**Exit criteria**

* Intentional abuses are blocked with useful errors; no RCE on default settings.

---

## Phase 17 — Nice-to-haves / next

* Streamlit helper (auto-wire session id).
* Redis session store adapter.
* Local web viewer for the SQLite logs.
* Start design for future “safe patch mode”.
* JS/TS adapter that calls the Python backend with the same spec files.

---

## Cut lines (if you need to ship earlier)

1. Ship after **Phase 7–9** for a usable MVP (specs, prompt, context docs, cache, contracts, examples).
2. Add **Phase 10–12** to stabilize in production (repair + deps + logging).
3. Add **Phase 13–15** for developer adoption (demos, perf, docs).

---

## Order-of-operations in the runtime (sanity check)

1. App calls `splice.run(name, session, prompt=… , **kwargs)` (prompt only on first call for that session+name).
2. Loader reads spec + config → docgen ensures needed docs exist.
3. Bundler assembles prompt (system prompts + contracts + docs + examples + **session prompt**).
4. OpenRouter returns one function → executor compiles/validates signature.
5. Cache artifact in SQLite → execute → return value.
6. Subsequent calls in the same session skip generation.

---

If you want, I can map each phase to a short test checklist so you know exactly what to verify before moving on.
