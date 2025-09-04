from __future__ import annotations

import sys
from pathlib import Path

import pytest

from splice.deps import DependencyPolicy


def test_if_present_requires_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = DependencyPolicy(policy="if-present")
    # Assume a stdlib module is present
    policy.ensure(["math"])  # should not raise
    # Non-existent module should raise
    with pytest.raises(Exception):
        policy.ensure(["this_module_does_not_exist_123"])  # noqa: S101


def test_allow_installs_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # We'll simulate install by mocking subprocess.run rather than actually installing
    calls: list[list[str]] = []

    def fake_run(args, check=False, stdout=None, stderr=None):  # type: ignore[no-untyped-def]
        calls.append([str(a) for a in args])
        class R:
            returncode = 0
        return R()

    import subprocess as sp
    monkeypatch.setattr(sp, "run", fake_run)

    # Force import to fail for a fake module to trigger install path
    module = "package_name_abc123xyz"
    sys.modules.pop(module, None)
    policy = DependencyPolicy(policy="allow")
    policy.ensure([module])
    assert calls, "pip should have been invoked"
    assert calls[0][0].endswith("python") or calls[0][0].endswith("python3")
    assert calls[0][-2:] == ["install", module]


