"""A stand-in code generator so the examples run without an API key.

Real projects use :class:`splice.OpenRouterClient` (the default). Anything
with a ``generate_code(bundle, config) -> str`` method can take its place,
which is also how the test suite stays deterministic.
"""

from __future__ import annotations

import re

from splice import PromptBundle, SpliceConfig

# Canned "model output" keyed by words that appear in the task prompt.
RECIPES: dict[str, str] = {
    "average": "def {name}(a: float, b: float) -> float:\n    return (a + b) / 2\n",
    "hypot": (
        "import math\n\ndef {name}(a: float, b: float) -> float:\n    return math.hypot(a, b)\n"
    ),
    "power": "def {name}(a: float, b: float) -> float:\n    return a ** b\n",
    "max": "def {name}(a: float, b: float) -> float:\n    return max(a, b)\n",
    # A model having a bad day: tries to exfiltrate credentials.
    "steal": (
        "import os\n\n"
        "def {name}(a: float, b: float) -> float:\n"
        "    key = os.environ.get('OPENROUTER_API_KEY', '')\n"
        "    open(os.path.expanduser('~/.ssh/id_ed25519')).read()\n"
        "    return float(len(key))\n"
    ),
    # A model that divides by zero on its first attempt.
    "harmonic": "def {name}(a: float, b: float) -> float:\n    return 2 / (1 / a + 1 / b) / 0\n",
}
REPAIRED_HARMONIC = "def {name}(a: float, b: float) -> float:\n    return 2 / (1 / a + 1 / b)\n"


class OfflineGenerator:
    """Pattern-matches the task prompt against a few canned recipes."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_code(self, bundle: PromptBundle, config: SpliceConfig) -> str:
        self.calls += 1
        text = bundle.text
        name = re.search(r"def\s+(\w+)\s*\(", text.split("CONTRACT SIGNATURE:", 1)[1])
        fn = name.group(1) if name else "op"
        task = text.split("TASK PROMPT:", 1)[1].split("EXAMPLES:", 1)[0].lower()
        if "previous generated function raised" in task:
            if "zerodivision" in task:
                return REPAIRED_HARMONIC.format(name=fn)
            return RECIPES["average"].format(name=fn)
        for keyword, template in RECIPES.items():
            if keyword in task:
                return template.format(name=fn)
        return RECIPES["max"].format(name=fn)
