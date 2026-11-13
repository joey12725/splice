"""Splice: generate a Python function from a prompt once, cache it, and run it sandboxed.

Importing this package has no side effects.
"""

from .client import GenerationError, OpenRouterClient
from .config import SandboxConfig, SpliceConfig
from .core import CodeGenerator, Session, Splice
from .errors import (
    ConfigError,
    DependenciesError,
    ExecutionError,
    ExecutionTimeout,
    PromptRequiredError,
    ResourceLimitExceeded,
    SandboxUnavailableError,
    SandboxViolation,
    SerializationError,
    SpecError,
    SpecNotFoundError,
    SpliceError,
    ValidationError,
    WorkspaceNotFoundError,
)
from .executor import Executor
from .prompt import PromptBundle, bundle_prompt
from .sandbox import ResourceLimits, Sandbox, SandboxPolicy, register_backend
from .specs import FunctionSpec

__version__ = "0.2.0"

__all__ = [
    "CodeGenerator",
    "ConfigError",
    "DependenciesError",
    "ExecutionError",
    "ExecutionTimeout",
    "Executor",
    "FunctionSpec",
    "GenerationError",
    "OpenRouterClient",
    "PromptBundle",
    "PromptRequiredError",
    "ResourceLimitExceeded",
    "ResourceLimits",
    "Sandbox",
    "SandboxConfig",
    "SandboxPolicy",
    "SandboxUnavailableError",
    "SandboxViolation",
    "SerializationError",
    "Session",
    "SpecError",
    "SpecNotFoundError",
    "Splice",
    "SpliceConfig",
    "SpliceError",
    "ValidationError",
    "WorkspaceNotFoundError",
    "__version__",
    "bundle_prompt",
    "register_backend",
]
