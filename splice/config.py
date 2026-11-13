"""Workspace configuration (``.splice/splice.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, WorkspaceNotFoundError
from .paths import require_splice_directory

DEFAULT_MODEL = "openai/gpt-5-mini"
DEFAULT_SYSTEM_PROMPT = (
    "You are a code generator. Output exactly one valid Python function that\n"
    "matches the declared signature and contracts. No explanations."
)
DEFAULT_ALLOW_IMPORTS: list[str] = ["math", "statistics", "numpy"]
REASONING_LEVELS = {"minimal": 0, "low": 1, "medium": 2, "high": 3}
SANDBOX_BACKENDS = ("auto", "process", "seatbelt", "bubblewrap", "docker", "podman")


@dataclass
class ModelConfig:
    name: str = DEFAULT_MODEL
    temperature: float = 0.2
    reasoning: int = 1
    system_prompt: str = DEFAULT_SYSTEM_PROMPT


@dataclass
class SessionsConfig:
    store: str = "sqlite"  # memory | sqlite | redis (sqlite is the implemented store)
    ttl: str = "24h"


@dataclass
class LoggingConfig:
    database: str = ".splice/db.sqlite"
    log_inputs: bool = False
    log_outputs: bool = False


@dataclass
class SandboxConfig:
    backend: str = "auto"
    allow_imports: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOW_IMPORTS))
    allow_fs: bool = False
    allow_net: bool = False
    allow_subprocess: bool = False
    restricted_python: bool = True
    timeout_seconds: float = 10.0
    cpu_seconds: int = 10
    memory_mb: int = 512
    max_file_size_mb: int = 16
    max_open_files: int = 64
    max_output_kb: int = 1024
    env_passthrough: list[str] = field(default_factory=list)
    python: str | None = None
    container_image: str = "python:3.12-slim"


@dataclass
class DependenciesConfig:
    policy: str = "if-present"  # off | if-present | allow


@dataclass
class RetriesConfig:
    generation: int = 2
    repair: int = 1


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a mapping")
    return value


def _bool(d: dict[str, Any], key: str, default: bool) -> bool:
    value = d.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"'{key}' must be true or false")
    return value


def _number(d: dict[str, Any], key: str, default: float, kind: type = int) -> Any:
    value = d.get(key, default)
    try:
        number = kind(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'{key}' must be a number") from exc
    if number < 0:
        raise ConfigError(f"'{key}' must not be negative")
    return number


def _str_list(d: dict[str, Any], key: str, default: list[str]) -> list[str]:
    value = d.get(key, default)
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ConfigError(f"sandbox.{key} must be a list of strings")
    return list(value)


def parse_reasoning(raw: Any) -> int:
    if isinstance(raw, str):
        level = raw.strip().lower()
        if level in REASONING_LEVELS:
            return REASONING_LEVELS[level]
        if level.lstrip("-").isdigit():
            return int(level)
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(raw)
    raise ConfigError("model.reasoning must be an integer or one of: minimal | low | medium | high")


@dataclass
class SpliceConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    dependencies: DependenciesConfig = field(default_factory=DependenciesConfig)
    retries: RetriesConfig = field(default_factory=RetriesConfig)

    @staticmethod
    def load(config_path: str | Path | None = None, start_path: Path | None = None) -> SpliceConfig:
        """Load config from YAML, applying defaults and validation.

        With no explicit path, ``.splice/splice.yaml`` is located by walking up
        from ``start_path`` (or the CWD). Missing files yield the defaults.
        """

        if config_path is not None:
            path = Path(config_path)
        else:
            try:
                path = require_splice_directory(start_path) / "splice.yaml"
            except WorkspaceNotFoundError:
                return SpliceConfig()

        if not path.exists():
            return SpliceConfig()

        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse config at {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Config at {path} must be a mapping")
        return SpliceConfig.from_dict(data)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SpliceConfig:
        m = _section(data, "model")
        model = ModelConfig(
            name=str(m.get("name", DEFAULT_MODEL)),
            temperature=_number(m, "temperature", 0.2, float),
            reasoning=parse_reasoning(m.get("reasoning", 1)),
            system_prompt=str(m.get("system_prompt", DEFAULT_SYSTEM_PROMPT)),
        )

        s = _section(data, "sessions")
        store = str(s.get("store", "sqlite"))
        if store not in {"memory", "sqlite", "redis"}:
            raise ConfigError("sessions.store must be one of: memory | sqlite | redis")
        sessions = SessionsConfig(store=store, ttl=str(s.get("ttl", "24h")))

        lg = _section(data, "logging")
        logging_cfg = LoggingConfig(
            database=str(lg.get("database", LoggingConfig.database)),
            log_inputs=_bool(lg, "log_inputs", False),
            log_outputs=_bool(lg, "log_outputs", False),
        )

        sb = _section(data, "sandbox")
        backend = str(sb.get("backend", "auto"))
        if backend not in SANDBOX_BACKENDS:
            from .sandbox import _BACKENDS  # custom registered backends are valid too

            if backend not in _BACKENDS:
                raise ConfigError(f"sandbox.backend must be one of: {' | '.join(SANDBOX_BACKENDS)}")
        python = sb.get("python")
        sandbox = SandboxConfig(
            backend=backend,
            allow_imports=_str_list(sb, "allow_imports", DEFAULT_ALLOW_IMPORTS),
            allow_fs=_bool(sb, "allow_fs", False),
            allow_net=_bool(sb, "allow_net", False),
            allow_subprocess=_bool(sb, "allow_subprocess", False),
            restricted_python=_bool(sb, "restricted_python", True),
            timeout_seconds=_number(sb, "timeout_seconds", 10.0, float),
            cpu_seconds=_number(sb, "cpu_seconds", 10),
            memory_mb=_number(sb, "memory_mb", 512),
            max_file_size_mb=_number(sb, "max_file_size_mb", 16),
            max_open_files=_number(sb, "max_open_files", 64),
            max_output_kb=_number(sb, "max_output_kb", 1024),
            env_passthrough=_str_list(sb, "env_passthrough", []),
            python=str(python) if python else None,
            container_image=str(sb.get("container_image", SandboxConfig.container_image)),
        )

        dp = _section(data, "dependencies")
        policy = str(dp.get("policy", "if-present"))
        if policy not in {"off", "if-present", "allow"}:
            raise ConfigError("dependencies.policy must be one of: off | if-present | allow")

        rt = _section(data, "retries")
        retries = RetriesConfig(
            generation=_number(rt, "generation", 2),
            repair=_number(rt, "repair", 1),
        )

        return SpliceConfig(
            model=model,
            sessions=sessions,
            logging=logging_cfg,
            sandbox=sandbox,
            dependencies=DependenciesConfig(policy=policy),
            retries=retries,
        )
