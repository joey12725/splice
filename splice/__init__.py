"""Splice package public API (Phase 0 scaffolding).

Importing this module should have no side effects.
"""

from .config import SpliceConfig
from .core import Session, Splice
from .specs import FunctionSpec
from .prompt import PromptBundle, bundle_prompt
from .client import OpenRouterClient, GenerationError
from .executor import Executor
from .errors import ExecutionError, SandboxViolation, SpecNotFoundError, WorkspaceNotFoundError

__all__ = [
    "Splice",
    "Session",
    "SpliceConfig",
    "FunctionSpec",
    "PromptBundle",
    "bundle_prompt",
    "OpenRouterClient",
    "GenerationError",
    "Executor",
    "ExecutionError",
    "SandboxViolation",
    "SpecNotFoundError",
    "WorkspaceNotFoundError",
]


