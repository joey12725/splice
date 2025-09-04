# 📘 Splice Requirements (v0.1)

## 1) Goals (unchanged essence)

* Let developers expose **LLM-generated, session-scoped code** that mutates real app objects.
* Every generated function has:

  * a **prompt** (provided once per session per function),
  * **contracts** (Python types/Pydantic) for inputs/outputs,
  * **context docs** (auto/manual) describing types available to the model.
* **Unsafe mutation only** for MVP (no patch mode).
* **Policies + runtime knobs** live in `splice.yaml`. Specs only describe the function.

---

## 2) Global config (`.splice/splice.yaml`)

> You asked to lock defaults and remove `provider`. Below is minimal but complete.
> The model section has only what you need; we’ll pass through whatever OpenRouter params you later add, but we don’t list the provider here.

```yaml
# .splice/splice.yaml
model:
  name: gpt-5                 # string; OpenRouter model id (provider implied elsewhere)
  temperature: 0.2
  reasoning: 1                # reasoning strength if supported
  system_prompt: |
    You are a code generator. Output exactly one valid Python function that
    matches the declared signature and contracts. No explanations.

# Session + logging defaults (locked for now)
sessions:
  store: sqlite               # memory | sqlite | redis (default: sqlite)
  ttl: 24h

logging:
  database: .splice/db.sqlite
  log_inputs: false
  log_outputs: false

# Sandbox + deps defaults (global only; not in specs)
sandbox:
  allow_imports: ["math", "statistics", "numpy"]
  allow_fs: false
  allow_net: false
  allow_subprocess: false

dependencies:
  policy: if-present          # off | if-present | allow

retries:
  generation: 2
  repair: 1
```

**Prompt scope rule (important):**

* The **prompt is required on the first call** to `splice.run(func_name, ..., session=..., prompt=...)` for that `(session, func_name)`.
* It is **cached per (session, func\_name)** and **must not** be provided/used across all sessions.
* Subsequent calls in the same session **omit** `prompt`.

---

## 3) Function spec files (YAML only)

* Location: `.splice/functions/*.yaml`
* Fields:

  * `name` (string)
  * `version` (semver)
  * `description` (string, free text)
  * `prompt` (string) – *this is the default prompt text to use when the app doesn’t supply one; still scoped per session per function*. Many apps will pass a user input instead; if you supply both, the runtime prefers the **call-time** prompt.
  * `system_prompt` (string, optional) – **function-level** system prompt (overrides global).
  * `contracts`:

    * `signature` – the exact Python signature the generator must implement
    * `inputs` – map of param name → Python type (string import path or builtin)
    * `output` – Python type (string import path or builtin)
    * `pydantic` (optional) – map of param/output → Pydantic model import paths
  * `context_docs` – list of doc names to include
  * `type_sources` – how to auto-generate those docs (class or instance)
  * `examples` – **few-shot pairs**: list of `{ prompt, function }`

> No JSON Schema. “Contracts” is now purely Python/Pydantic and can reference any type (builtins, third-party, or your own). Docgen will introspect types you list in `type_sources` and produce `.splice/context/<Type>.md` once (first run or via CLI).

---

## 4) Example specs

### 4.1 Generic simulation hook (generic name, unsafe mutation)

**File:** `.splice/functions/generic_simulation_hook.yaml`

```yaml
name: generic_simulation_hook
version: 0.1.0
description: |
  Session-scoped hook that modifies a user's state each timestep according to
  a natural-language prompt. Intended for scenario comparisons.

# Default text if the app doesn't provide a prompt at call time.
# Still cached per (session, name); never shared across sessions.
prompt: |
  Describe your custom scenario. Example:
  "At timestep 11–12, pause payments on the boat loan and add a $25 fee."

# Optional function-level system prompt
system_prompt: |
  Output exactly one Python function:
  def generic_simulation_hook(user, timestep: int, market=None) -> User

contracts:
  signature: "def generic_simulation_hook(user, timestep: int, market=None) -> User"
  inputs:
    user: "app.models.User"                      # any type is allowed
    timestep: "int"
    market: "typing.Optional[app.models.Market]"
  output: "app.models.User"
  pydantic:
    user: "app.models.UserModel"                 # optional
    market: "app.models.MarketModel"
    output: "app.models.UserModel"

context_docs:
  - User
  - Asset
  - Loan
  - InterestModel
  - DataFrame

type_sources:
  - name: User
    import: "app.domain.user.User"
    doc_strategy: class
  - name: Asset
    import: "app.domain.asset.Asset"
    doc_strategy: class
  - name: Loan
    import: "app.domain.loan.Loan"
    doc_strategy: class
  - name: InterestModel
    import: "app.domain.rate.InterestModel"
    doc_strategy: class
  - name: DataFrame
    import: "pandas.DataFrame"
    doc_strategy: class

examples:
  - prompt: |
      Pause payments for two months and add a $25 fee in month 12.
    function: |
      def generic_simulation_hook(user, timestep: int, market=None) -> User:
          if 'boat' in user.loans and timestep in (11, 12):
              loan = user.loans['boat']
              # accrue monthly interest
              loan.balance += loan.balance * (loan.rate / 12.0)
              # add fee in month 12
              if timestep == 12:
                  loan.balance += 25.0
          return user

  - prompt: |
      Starting at timestep 24, increase APR by 1.5 percentage points.
    function: |
      def generic_simulation_hook(user, timestep: int, market=None) -> User:
          if 'boat' in user.loans and timestep >= 24:
              loan = user.loans['boat']
              loan.rate += 0.015
              loan.balance += loan.balance * (loan.rate / 12.0)
          return user
```

### 4.2 Generic operand (trivial calc; still contract-based)

**File:** `.splice/functions/generic_operand.yaml`

```yaml
name: generic_operand
version: 0.1.0
description: |
  Binary numeric operation from a natural-language prompt (a, b) -> float.

prompt: |
  Describe the operation using 'a' and 'b' (e.g., "a^b + 1").

system_prompt: |
  Output exactly one Python function:
  def generic_operand(a: float, b: float) -> float

contracts:
  signature: "def generic_operand(a: float, b: float) -> float"
  inputs:
    a: "float"
    b: "float"
  output: "float"

context_docs: []
type_sources: []

examples:
  - prompt: "Compute geometric mean"
    function: |
      def generic_operand(a: float, b: float) -> float:
          return (a * b) ** 0.5

  - prompt: "Return max(a, b)"
    function: |
      def generic_operand(a: float, b: float) -> float:
          return max(a, b)
```

---

## 5) Runtime API (MVP)

```python
from splice import Splice, Session

splice = Splice(config_path=".splice/splice.yaml")
sess = Session.ensure()  # your framework can supply/propagate this token

# First call for this (session, function): provide prompt
user = splice.run(
    "generic_simulation_hook",
    session=sess,
    prompt="Pause boat loan payments for 2 months; add $25 fee in month 12.",
    user=current_user,
    timestep=t,
    market=market_data,
)

# Later calls in the same session: omit prompt (code already generated & cached)
user = splice.run(
    "generic_simulation_hook",
    session=sess,
    user=current_user,
    timestep=t+1,
    market=market_data,
)
```

**Behavior**

* One LLM call on first hit per `(session, func_name)` (prompt is part of the cache key).
* Generated code runs in a sandboxed child process (unsafe mutation allowed).
* Inputs/outputs validated via `contracts` (Python types / optional Pydantic).
* Auto-repair & retries follow `splice.yaml`.
* All artifacts/logs cached in `.splice/db.sqlite`.

---

## 6) CLI (minimal)

* `splice init` → scaffold `.splice/` + `splice.yaml`
* `splice docgen --types User Asset Loan pandas.DataFrame` → produce `.splice/context/*.md`
* `splice make-func generic_simulation_hook --auto`
  (prefill spec by scanning nearby code + LLM; `--minimal` for bare template)
* `splice cache purge` → clear cache & wipe `.splice/db.sqlite`

---

## 7) Notes on “any type” support

* **contracts.inputs/output** can reference **any** Python type (e.g., `numpy.ndarray`, `pandas.DataFrame`, your classes).
* Add those types under **type\_sources** so Splice can introspect and write `.splice/context/<Type>.md` on first run (or via CLI).
* You can override those docs by editing the Markdown files—Splice prefers your manual content.

