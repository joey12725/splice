# Splice (Phases 0–3)

Minimal scaffolding through Phase 3.

Install (editable):

```bash
pip install -e .[dev]
```

## Environment

Set your OpenRouter API key (do not hardcode):

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

## Usage

Imports and Phase 2 prompt bundling:

```python
from splice import Splice, Session, SpliceConfig, bundle_prompt

splice = Splice()
s = Session.ensure()

# Load config (defaults if .splice/splice.yaml missing)
cfg = SpliceConfig.load()

# Suppose you already loaded a FunctionSpec as `spec`
# from splice import FunctionSpec; spec = splice.spec("generic_operand")
bundle = bundle_prompt(spec, cfg, session_prompt="Compute geometric mean of a and b")
```

Phase 3: generate code via OpenRouter:

```python
from splice import OpenRouterClient

client = OpenRouterClient()
code_str = client.generate_code(bundle, cfg)
print(code_str)
```



