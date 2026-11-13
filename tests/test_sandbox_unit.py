"""Unit tests for the sandbox plumbing: codec, policy wiring, backend commands."""

from __future__ import annotations

import datetime as dt
import decimal
import fractions
import json
import math
import uuid
from pathlib import Path

import pytest

from splice.config import SandboxConfig, SpliceConfig
from splice.errors import ConfigError, SandboxUnavailableError
from splice.sandbox import (
    ContainerSandbox,
    ExecutionRequest,
    ExecutionResult,
    ProcessSandbox,
    Sandbox,
    SandboxPolicy,
    available_backends,
    create_sandbox,
    policy_from_config,
    register_backend,
    resolve_backend_name,
)
from splice.sandbox._runner import check_source, decode_value, encode_value
from splice.sandbox.bubblewrap import build_bwrap_args
from splice.sandbox.process import build_env
from splice.sandbox.seatbelt import build_profile

# --------------------------------------------------------------------------- codec


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        0,
        -(2**80),
        1.25,
        "text",
        b"\x00bytes",
        bytearray(b"ba"),
        [1, [2, [3]]],
        (1, (2, 3)),
        {"a": 1},
        {1: "int key", (1, 2): "tuple key"},
        {"$splice": "user data that looks like a tag"},
        {1, 2, 3},
        frozenset({"x"}),
        complex(1, -2),
        decimal.Decimal("1.10"),
        fractions.Fraction(1, 3),
        dt.datetime(2026, 1, 2, 3, 4, 5),
        dt.date(2026, 1, 2),
        dt.time(3, 4, 5),
        dt.timedelta(days=1, seconds=2, microseconds=3),
        uuid.UUID(int=7),
    ],
)
def test_codec_round_trip(value: object) -> None:
    wire = json.loads(json.dumps(encode_value(value), allow_nan=False))
    assert decode_value(wire) == value
    assert type(decode_value(wire)) is type(value)


def test_codec_special_floats() -> None:
    for f in (math.inf, -math.inf):
        assert decode_value(encode_value(f)) == f
    assert math.isnan(decode_value(encode_value(math.nan)))


def test_codec_rejects_arbitrary_objects() -> None:
    class Custom:
        pass

    with pytest.raises(TypeError):
        encode_value(Custom())


def test_decoder_rejects_unknown_tags() -> None:
    with pytest.raises(ValueError):
        decode_value({"$splice": "pickle", "v": "gASV..."})


def test_codec_numpy_arrays() -> None:
    np = pytest.importorskip("numpy")
    arr = np.arange(6, dtype="int32").reshape(2, 3)
    out = decode_value(json.loads(json.dumps(encode_value(arr))))
    assert out.dtype == arr.dtype and (out == arr).all()


# --------------------------------------------------------------------------- static guard


def test_check_source_allows_plain_code() -> None:
    check_source(
        "import math\ndef f(x):\n    return math.sqrt(x).__doc__\n", {"allow_imports": ["math"]}
    )


@pytest.mark.parametrize(
    "code",
    [
        "from . import x",
        "x = ().__class__",
        "x = getattr",
        "import socket",
    ],
)
def test_check_source_rejects(code: str) -> None:
    from splice.sandbox._runner import SandboxDenied

    with pytest.raises(SandboxDenied):
        check_source(code, {"allow_imports": ["math", "socket"]})


# --------------------------------------------------------------------------- policy and env


def test_policy_from_config_copies_limits_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISIBLE_TOKEN", "abc")
    monkeypatch.setenv("HIDDEN_TOKEN", "xyz")
    cfg = SandboxConfig(memory_mb=128, cpu_seconds=3, env_passthrough=["VISIBLE_TOKEN"])
    policy = policy_from_config(cfg, timeout_seconds=2.5)
    assert policy.limits.memory_mb == 128
    assert policy.limits.cpu_seconds == 3
    assert policy.limits.timeout_seconds == 2.5
    assert dict(policy.env) == {"VISIBLE_TOKEN": "abc"}


def test_child_env_is_built_from_scratch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    env = build_env(SandboxPolicy(), "/tmp/work")
    assert "OPENROUTER_API_KEY" not in env
    assert env["HOME"] == "/tmp/work"
    assert set(env) <= {
        "PATH",
        "LANG",
        "LC_ALL",
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    }


def test_sandbox_config_parsing(tmp_path: Path) -> None:
    path = tmp_path / "splice.yaml"
    path.write_text(
        "sandbox:\n  backend: process\n  memory_mb: 64\n  timeout_seconds: 1.5\n"
        "  env_passthrough: [FOO]\n"
    )
    cfg = SpliceConfig.load(path)
    assert cfg.sandbox.backend == "process"
    assert cfg.sandbox.memory_mb == 64
    assert cfg.sandbox.timeout_seconds == 1.5
    assert cfg.sandbox.env_passthrough == ["FOO"]


@pytest.mark.parametrize(
    "body",
    [
        "sandbox:\n  backend: chroot\n",
        "sandbox:\n  memory_mb: -1\n",
        "sandbox:\n  allow_net: 'yes'\n",
        "sandbox:\n  allow_imports: math\n",
    ],
)
def test_sandbox_config_validation(tmp_path: Path, body: str) -> None:
    path = tmp_path / "splice.yaml"
    path.write_text(body)
    with pytest.raises(ConfigError):
        SpliceConfig.load(path)


# --------------------------------------------------------------------------- registry


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    import splice.sandbox as sandbox_pkg

    monkeypatch.setattr(sandbox_pkg, "_BACKENDS", dict(sandbox_pkg._BACKENDS))


def test_auto_picks_an_available_backend() -> None:
    name = resolve_backend_name("auto")
    assert available_backends()[name]


def test_unknown_backend_name() -> None:
    with pytest.raises(ConfigError):
        resolve_backend_name("nope")


def test_unavailable_backend_is_reported() -> None:
    class Never(ProcessSandbox):
        name = "never"

        @classmethod
        def is_available(cls) -> bool:
            return False

    register_backend("never", Never)
    with pytest.raises(SandboxUnavailableError):
        resolve_backend_name("never")


def test_custom_backend_plugs_in() -> None:
    class Echo(Sandbox):
        name = "echo"

        def execute(self, request: ExecutionRequest, policy: SandboxPolicy) -> ExecutionResult:
            return ExecutionResult(value=dict(request.kwargs), backend=self.name)

    register_backend("echo", Echo)
    sandbox = create_sandbox(SandboxConfig(backend="echo"))
    assert isinstance(sandbox, Echo)

    from splice import Executor

    cfg = SpliceConfig(sandbox=SandboxConfig(backend="echo"))
    assert Executor.run("def f(x): ...", "def f(x)", {"x": 1}, cfg) == {"x": 1}


# --------------------------------------------------------------------------- OS wrappers


def test_seatbelt_profile_is_deny_by_default() -> None:
    profile = build_profile(policy=SandboxPolicy(), workdir="/w", python="/usr/bin/python3")
    assert profile.splitlines()[1] == "(deny default)"
    assert "network" not in profile
    assert "process-fork" not in profile
    assert '(allow file-read* (subpath "/w"))' in profile
    assert "file-write* (subpath" not in profile


def test_seatbelt_profile_opt_ins() -> None:
    policy = SandboxPolicy(allow_fs=True, allow_net=True, allow_subprocess=True)
    profile = build_profile(policy=policy, workdir="/w", python="/usr/bin/python3")
    assert '(allow file-read* file-write* (subpath "/w"))' in profile
    assert "(allow network*)" in profile
    assert "(allow process-fork)" in profile


def test_bwrap_args_unshare_everything() -> None:
    args = build_bwrap_args(policy=SandboxPolicy(), workdir="/w", python="/usr/bin/python3")
    assert "--unshare-all" in args
    assert "--share-net" not in args
    assert "--die-with-parent" in args
    i = args.index("/w")
    assert args[i - 1] == "--ro-bind"


def test_bwrap_args_network_and_fs_opt_in() -> None:
    policy = SandboxPolicy(allow_net=True, allow_fs=True)
    args = build_bwrap_args(policy=policy, workdir="/w", python="/usr/bin/python3")
    assert "--share-net" in args
    assert args[args.index("/w") - 1] == "--bind"


def test_container_command_is_locked_down() -> None:
    cmd = ContainerSandbox(image="python:3.12-slim").build_command(SandboxPolicy(), "splice-x")
    joined = " ".join(cmd)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 65534:65534",
        "--memory 512m",
        "--memory-swap 512m",
        "--pids-limit 16",
    ):
        assert flag in joined
    assert "python:3.12-slim" in cmd


def test_container_network_opt_in() -> None:
    cmd = ContainerSandbox().build_command(SandboxPolicy(allow_net=True), "splice-x")
    assert cmd[cmd.index("--network") + 1] == "bridge"
