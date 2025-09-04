# Splice

Session-scoped LLM code executor with sandboxing, caching, and a simple CLI.

### Install

```bash
pip install -e .[dev]
```

### Environment

Set your OpenRouter API key (do not hardcode):

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

### Quickstart

```bash
# Initialize a local workspace
splice init

# Create a function spec skeleton
splice make-func my_op

# Generate docs for types/classes into .splice/context
splice docgen --types collections.Counter datetime.datetime
```

Run a function with session-scoped caching:

```python
from splice import Splice, Session

s = Session.ensure()
result = Splice().run(
    "my_op",
    session=s,
    prompt="Return (a + b) / 2",
    a=4.0,
    b=6.0,
)
print(result)
```

### Demo: Calculator with dynamic `?` operator

This repository includes a demo calculator that supports `+ - * /` and a special `?` operator. The first time you use `?` in a session, it prompts you to describe the behavior in natural language, then uses Splice to generate and cache an implementation for the rest of the session.

Run interactively:

```bash
splice-demo-calculator
# enter: 5?9
# define behavior, e.g. "return a**2 + b**2"
```

Or one-off:

```bash
splice-demo-calculator "3?4"
```

### Development

Run tests and linters:

```bash
pytest -q
ruff check .
mypy splice
```

