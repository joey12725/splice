## Configuration

Global config lives at `.splice/splice.yaml`. If missing, defaults are used.

### Example
```yaml
model:
  name: openai/gpt-5-mini
  temperature: 0.2
  reasoning: 1
  system_prompt: |
    You are a code generator. Output exactly one valid Python function that
    matches the declared signature and contracts. No explanations.

sessions:
  store: sqlite
  ttl: 24h

logging:
  database: .splice/db.sqlite

sandbox:
  allow_imports: ["math", "statistics", "numpy"]
  allow_fs: false
  allow_net: false
  allow_subprocess: false

dependencies:
  policy: if-present  # off | if-present | allow

retries:
  generation: 2
  repair: 1
```

### Access programmatically
```python
from splice import SpliceConfig

cfg = SpliceConfig.load()
print(cfg.model.name)
```

### Edit via CLI
You can update common configuration fields with `splice edit`:

```bash
# Model and reasoning
splice edit --set-model openai/gpt-5-mini --set-reasoning high

# System prompt (inline or from file)
splice edit --set-system-prompt-text "You are precise."
splice edit --set-system-prompt-file ./system.txt

# Sandbox controls
splice edit --set-sandbox-imports numpy,pandas --enable-net --disable-fs

# Dependency policy and retries
splice edit --set-deps-policy allow --set-retries-generation 3 --set-retries-repair 2
```


