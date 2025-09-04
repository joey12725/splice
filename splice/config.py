from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .paths import require_splice_directory

DEFAULT_ALLOW_IMPORTS: list[str] = ["math", "statistics", "numpy"]


@dataclass
class ModelConfig:
    name: str = "openai/gpt-5-mini"
    temperature: float = 0.2
    reasoning: int = 1
    system_prompt: str = (
        "You are a code generator. Output exactly one valid Python function that\n"
        "matches the declared signature and contracts. No explanations."
    )


@dataclass
class SessionsConfig:
    store: str = "sqlite"  # memory | sqlite | redis
    ttl: str = "24h"


@dataclass
class LoggingConfig:
    database: str = ".splice/db.sqlite"
    log_inputs: bool = False
    log_outputs: bool = False


@dataclass
class SandboxConfig:
    allow_imports: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOW_IMPORTS))
    allow_fs: bool = False
    allow_net: bool = False
    allow_subprocess: bool = False


@dataclass
class DependenciesConfig:
    policy: str = "if-present"  # off | if-present | allow


@dataclass
class RetriesConfig:
    generation: int = 2
    repair: int = 1


@dataclass
class SpliceConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    sessions: SessionsConfig = field(default_factory=SessionsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    dependencies: DependenciesConfig = field(default_factory=DependenciesConfig)
    retries: RetriesConfig = field(default_factory=RetriesConfig)

    @staticmethod
    def load(config_path: str | None = None, start_path: Path | None = None) -> SpliceConfig:
        """Load config from YAML, applying defaults and validation."""

        # Resolve path: explicit wins; else find .splice/splice.yaml
        if config_path is not None:
            path = Path(config_path)
        else:
            base = require_splice_directory(start_path)
            path = base / "splice.yaml"

        if not path.exists():
            # Return defaults if file isn't present yet
            return SpliceConfig()

        try:
            data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        except Exception as exc:  # pragma: no cover
            raise ConfigError(f"Failed to parse config at {path}: {exc}") from exc

        # Construct nested configs with defaults and overrides
        def model_from(d: dict[str, Any]) -> ModelConfig:
            # Map reasoning: accept int or enum string minimal|low|medium|high
            raw_reasoning = d.get("reasoning", ModelConfig.reasoning)
            reasoning_value: int
            if isinstance(raw_reasoning, str):
                level = raw_reasoning.strip().lower()
                mapping = {
                    "minimal": 0,
                    "low": 1,
                    "medium": 2,
                    "high": 3,
                }
                if level in mapping:
                    reasoning_value = mapping[level]
                else:
                    raise ConfigError(
                        "model.reasoning must be an integer or one of: minimal | low | medium | high"
                    )
            else:
                try:
                    reasoning_value = int(raw_reasoning)
                except Exception as exc:  # noqa: BLE001
                    raise ConfigError(
                        "model.reasoning must be an integer or one of: minimal | low | medium | high"
                    ) from exc

            return ModelConfig(
                name=str(d.get("name", ModelConfig.name)),
                temperature=float(d.get("temperature", ModelConfig.temperature)),
                reasoning=reasoning_value,
                system_prompt=str(d.get("system_prompt", ModelConfig.system_prompt)),
            )

        def sessions_from(d: dict[str, Any]) -> SessionsConfig:
            store = str(d.get("store", SessionsConfig.store))
            if store not in {"memory", "sqlite", "redis"}:
                raise ConfigError("sessions.store must be one of: memory | sqlite | redis")
            return SessionsConfig(store=store, ttl=str(d.get("ttl", SessionsConfig.ttl)))

        def logging_from(d: dict[str, Any]) -> LoggingConfig:
            return LoggingConfig(
                database=str(d.get("database", LoggingConfig.database)),
                log_inputs=bool(d.get("log_inputs", LoggingConfig.log_inputs)),
                log_outputs=bool(d.get("log_outputs", LoggingConfig.log_outputs)),
            )

        def sandbox_from(d: dict[str, Any]) -> SandboxConfig:
            allow_imports = d.get("allow_imports", DEFAULT_ALLOW_IMPORTS)
            is_list = isinstance(allow_imports, list)
            has_only_str = is_list and all(isinstance(x, str) for x in allow_imports)
            if not (is_list and has_only_str):
                raise ConfigError(
                    "sandbox.allow_imports must be a list of strings"
                )
            return SandboxConfig(
                allow_imports=list(allow_imports),
                allow_fs=bool(d.get("allow_fs", SandboxConfig.allow_fs)),
                allow_net=bool(d.get("allow_net", SandboxConfig.allow_net)),
                allow_subprocess=bool(d.get("allow_subprocess", SandboxConfig.allow_subprocess)),
            )

        def dependencies_from(d: dict[str, Any]) -> DependenciesConfig:
            policy = str(d.get("policy", DependenciesConfig.policy))
            if policy not in {"off", "if-present", "allow"}:
                raise ConfigError("dependencies.policy must be one of: off | if-present | allow")
            return DependenciesConfig(policy=policy)

        def retries_from(d: dict[str, Any]) -> RetriesConfig:
            return RetriesConfig(
                generation=int(d.get("generation", RetriesConfig.generation)),
                repair=int(d.get("repair", RetriesConfig.repair)),
            )

        model_cfg = model_from(data.get("model", {}))
        sessions_cfg = sessions_from(data.get("sessions", {}))
        logging_cfg = logging_from(data.get("logging", {}))
        sandbox_cfg = sandbox_from(data.get("sandbox", {}))
        deps_cfg = dependencies_from(data.get("dependencies", {}))
        retries_cfg = retries_from(data.get("retries", {}))

        return SpliceConfig(
            model=model_cfg,
            sessions=sessions_cfg,
            logging=logging_cfg,
            sandbox=sandbox_cfg,
            dependencies=deps_cfg,
            retries=retries_cfg,
        )


