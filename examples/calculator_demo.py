"""A calculator with a user-defined ``?`` operator.

The first time you use ``?`` you describe it in English ("the hypotenuse of a
right triangle with legs a and b"). Splice generates the function, runs it in
the sandbox, and reuses the cached code for every later ``?``.

    python examples/calculator_demo.py              # interactive, live model
    python examples/calculator_demo.py --offline    # canned generator, no API key
    python examples/calculator_demo.py --offline --define "hypotenuse" "3?4"
"""

from __future__ import annotations

import argparse
import operator
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from offline import OfflineGenerator

from splice import Session, Splice
from splice.cli import cmd_init

OPS: dict[str, Callable[[float, float], float]] = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
}
SPEC = Path(__file__).resolve().parent / "specs" / "blend.yaml"


def parse(expr: str) -> tuple[float, str, float]:
    expr = expr.strip()
    for op in ["?", "+", "*", "/", "-"]:
        left, sep, right = expr.partition(op)
        if sep and left.strip():
            return float(left), op, float(right)
    raise ValueError("expected an expression like 3+4 or 5?9")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculator with an LLM-defined ? operator")
    parser.add_argument("expressions", nargs="*", help="expressions to evaluate, e.g. 3?4")
    parser.add_argument("--offline", action="store_true", help="use the canned generator")
    parser.add_argument("--define", help="meaning of ? (skips the interactive question)")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="splice-calc-") as tmp:
        root = Path(tmp)
        base = cmd_init(start_path=root, quiet=True)
        shutil.copy(SPEC, base / "functions" / "blend.yaml")
        sp = Splice(client=OfflineGenerator() if args.offline else None)
        session = Session.ensure()
        meaning = args.define
        defined = False

        def evaluate(text: str) -> float:
            nonlocal meaning, defined
            a, op, b = parse(text)
            if op != "?":
                return OPS[op](a, b)
            if meaning is None:
                meaning = input("What should ? do? ").strip() or "the larger of a and b"
            prompt = None if defined else meaning
            defined = True
            return float(sp.run("blend", session=session, start_path=root, prompt=prompt, a=a, b=b))

        if args.expressions:
            for expr in args.expressions:
                print(f"{expr} = {evaluate(expr)}")
            return 0

        print("Enter expressions like 5?9 or 3+4. Ctrl-D to exit.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if line:
                try:
                    print(evaluate(line))
                except Exception as exc:
                    print(f"error: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
