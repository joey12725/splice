## Quickstart

This guide walks you through creating your first function with Splice.

### 1) Install and set up
```bash
pip install -e '.[dev]'
export OPENROUTER_API_KEY="sk-or-..."
```

### 2) Initialize the workspace
```bash
splice init
```

### 3) Scaffold a function spec
```bash
splice edit --add-func my_op
```

This creates `.splice/functions/my_op.yaml`. Edit it as needed.

### 4) (Optional) Generate docs for referenced types
```bash
splice edit --doc-class collections.Counter datetime.datetime
```

### 5) Call your function
```python
from splice import Splice, Session

session = Session.ensure()
res = Splice().run(
  "my_op",
  session=session,
  prompt="Return (a + b) / 2",
  a=2.0,
  b=4.0,
)
print(res)
```

If you only want to generate code now and run later (no test data yet):
```python
from splice import Splice, Session

sess = Session.ensure()
# Caches generated code but does not execute and returns None
Splice().run("my_op", session=sess, prompt="Return (a + b) / 2", run_now=False)
# Later, execute with inputs; first run will still auto-repair on errors
print(Splice().run("my_op", session=sess, a=2.0, b=4.0))
```

Next steps:
- Explore the [Function Specs](./specs.md)
- Configure the [Sandbox and Cache](./runtime.md)


