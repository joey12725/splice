"""Splice in one screen: generate once, cache, sandbox, self-repair.

Runs offline by default with a canned generator. Pass ``--live`` to use
OpenRouter (needs ``OPENROUTER_API_KEY``).

    python examples/quickstart.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from offline import RECIPES, OfflineGenerator

from splice import Executor, SandboxViolation, Session, Splice, SpliceConfig
from splice.cli import cmd_init
from splice.sandbox import resolve_backend_name

SPEC = Path(__file__).resolve().parent / "specs" / "blend.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="use OpenRouter instead of canned code")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="splice-demo-") as tmp:
        root = Path(tmp)
        base = cmd_init(start_path=root, quiet=True)
        shutil.copy(SPEC, base / "functions" / "blend.yaml")

        generator = None if args.live else OfflineGenerator()
        sp = Splice(client=generator)
        session = Session.ensure()
        print(f"sandbox backend: {resolve_backend_name('auto')}\n")

        # 1. First call: the prompt defines the behaviour; code is generated and cached.
        value = sp.run(
            "blend",
            session=session,
            start_path=root,
            prompt="Return the average of a and b",
            a=4.0,
            b=6.0,
        )
        print(f"blend(4, 6)             -> {value}")

        # 2. Later calls in the session reuse the cached function. No model call.
        started = time.perf_counter()
        for i in range(20):
            sp.run("blend", session=session, start_path=root, a=float(i), b=10.0)
        per_call = (time.perf_counter() - started) / 20 * 1000
        calls = generator.calls if generator else "n/a"
        print(f"20 more calls           -> {per_call:.0f} ms each, model calls so far: {calls}")

        # 3. Whatever the model writes runs in the sandbox, never in this process.
        try:
            Executor.run(
                RECIPES["steal"].format(name="blend"),
                "def blend(a, b)",
                {"a": 1.0, "b": 2.0},
                SpliceConfig(),
            )
        except SandboxViolation as exc:
            print(f"credential grab         -> blocked: {exc}")

        # 4. Runtime errors are fed back to the model and repaired automatically.
        value = sp.run(
            "blend",
            session=Session.ensure(),
            start_path=root,
            prompt="Return the harmonic mean of a and b",
            a=3.0,
            b=6.0,
        )
        print(f"harmonic(3, 6)          -> {value}  (after one repair round)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
