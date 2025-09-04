## CLI

Splice ships a minimal CLI for initialization, editing your workspace, generating docs, and utilities.

### Commands
- `splice init [--wizard]`
  - Create `.splice/` with `functions/`, `context/`, and a default `splice.yaml`.
- `splice edit`
  - Interactive editor with a guided menu. Launches a TUI when run with no flags:
    - Functions: add or edit function specs with guided prompts or your `$EDITOR`.
    - Documentation: generate docs for classes (guided) or from a URL, or open existing docs.
    - Configuration: update model, system prompt, sandbox, dependency policy, and retries with guardrails.
  - You can also use non-interactive flags to script specific actions:
    - `--add-func <name> [more...]` and `--func-mode [minimal|auto]`
    - `--doc-class <Import.Path> [More.Paths...]`
    - `--doc-url <URL> --doc-url-name <Name>` (scrapes URL and summarizes with LLM)
    - Config updates:
      - `--set-model <model>`
      - `--set-system-prompt-text <text>` or `--set-system-prompt-file <path>`
      - `--set-reasoning <int|minimal|low|medium|high>`
      - `--set-sandbox-imports a,b,c`
      - `--enable-fs|--disable-fs`, `--enable-net|--disable-net`, `--enable-subprocess|--disable-subprocess`
      - `--set-deps-policy off|if-present|allow`
      - `--set-retries-generation <n>`, `--set-retries-repair <n>`
- `splice cache purge`
  - Clear cached artifacts.
- `splice --version`
  - Print the installed version.

### Legacy commands
- `splice make-func <name> [--minimal|--auto]` and `splice docgen --types ...` remain available for backward compatibility, but `splice edit` replaces both.

### Examples
```bash
# Init
splice init --wizard

# Add function specs
splice edit --add-func compute_interest discount_rate --func-mode auto

# Generate docs for classes/types in your environment
splice edit --doc-class pandas.DataFrame numpy.ndarray

# Generate docs from an external documentation URL
splice edit --doc-url https://pandas.pydata.org/docs/ --doc-url-name pandas

# Update config
splice edit --set-model openai/gpt-5-mini --set-reasoning high
splice edit --set-system-prompt-file ./system.txt
splice edit --set-sandbox-imports numpy,pandas --enable-net --disable-fs
splice edit --set-deps-policy allow --set-retries-generation 3 --set-retries-repair 2

# Utilities
splice cache purge
```

### Interactive mode preview
Running `splice edit` opens a simple, readable menu. Use single-letter choices and Enter to navigate. Wherever applicable, fields explain what they do and you can leave them blank to keep current values. If `$EDITOR` is set, choosing “open in editor” will open the targeted file.


