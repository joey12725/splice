from __future__ import annotations

import operator

from splice import Session, Splice


OPS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": operator.truediv}


def _parse(s: str) -> tuple[float, str, float]:
    s = s.strip()
    for op in ["?", "+", "-", "*", "/"]:
        if op in s:
            a, b = s.split(op, 1)
            return float(a.strip()), op, float(b.strip())
    raise ValueError("need one of + - * / ?")


def main(argv: list[str] | None = None) -> int:
    # Require a project-local .splice/; instruct user to init if missing
    from splice.paths import require_splice_directory
    try:
        require_splice_directory(None)
    except Exception as exc:
        raise SystemExit(f"{exc}")

    s = Session.ensure(); sp = Splice(); q = None

    def eval_expr(text: str) -> float:
        nonlocal q
        a, op, b = _parse(text)
        if op != "?":
            return float(OPS[op](a, b))
        if q is None:
            print("Define ?: ", end=""); q = input().strip()
            if not q:
                raise SystemExit("no behavior for ?")
            return float(sp.run("generic_operand", session=s, prompt=q, a=a, b=b))
        return float(sp.run("generic_operand", session=s, a=a, b=b))

    if argv and len(argv) > 0:
        print(eval_expr(argv[0])); return 0
    print("Enter expressions like '5?9' or '3+4'. Ctrl-C to exit.")
    try:
        while True:
            line = input("> ").strip()
            if not line:
                continue
            print(eval_expr(line))
    except KeyboardInterrupt:
        print(); return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


