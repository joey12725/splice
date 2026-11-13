# Quickstart

## 1. Install

```bash
git clone https://github.com/joey12725/splice.git
cd splice
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.10+ on macOS or Linux. On Linux, `apt install bubblewrap` (or your
distro's equivalent) enables the namespace sandbox; macOS uses the built-in
`sandbox-exec`.

## 2. Try it offline

```bash
python examples/quickstart.py
python examples/calculator_demo.py --offline --define "hypotenuse" "3?4" "5?12"
```

Both use a canned code generator, so no API key is needed.

## 3. Your own workspace

```bash
export OPENROUTER_API_KEY="..."
splice init                     # creates .splice/ with functions/, context/, splice.yaml
splice edit --add-func my_op    # scaffolds .splice/functions/my_op.yaml
splice sandbox                  # shows which sandbox backend will run your code
```

Edit `.splice/functions/my_op.yaml` to declare the contract (see
[specs](specs.md)), then:

```python
from splice import Session, Splice

session = Session.ensure()
print(Splice().run("my_op", session=session, prompt="Return (a + b) / 2", a=2.0, b=4.0))
print(Splice().run("my_op", session=session, a=10.0, b=20.0))  # cached, no model call
```

Generate now, run later (no test data yet):

```python
Splice().run("my_op", session=session, prompt="Return (a + b) / 2", run_now=False)
```

Next: [configuration](config.md) and the [sandbox security model](../security.md).
