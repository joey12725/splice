"""Exception hierarchy for Splice."""

from __future__ import annotations


class SpliceError(Exception):
    """Base class for Splice exceptions."""


class ConfigError(SpliceError):
    """Raised when the global config is invalid."""


class SpecError(SpliceError):
    """Raised when a function spec is invalid or missing."""


class SpecNotFoundError(SpecError):
    """Raised when a function spec YAML cannot be found in the expected location."""


class PromptRequiredError(SpliceError, ValueError):
    """Raised when no cached code exists and no prompt was given to generate it."""


class GenerationError(SpliceError):
    """Raised when code generation fails or a valid function cannot be extracted."""


class ExecutionError(SpliceError):
    """Raised when executing generated code fails."""


class SerializationError(ExecutionError):
    """Raised when an argument or return value cannot cross the sandbox boundary."""


class ResourceLimitExceeded(ExecutionError):
    """Raised when generated code exceeds a CPU, memory, output or file-size limit."""


class ExecutionTimeout(ResourceLimitExceeded):
    """Raised when generated code exceeds its wall-clock budget."""


class SandboxViolation(SpliceError):
    """Raised when generated code attempts a disallowed operation in the sandbox."""


class SandboxUnavailableError(SpliceError):
    """Raised when the configured sandbox backend cannot run on this machine."""


class ValidationError(SpliceError):
    """Raised when inputs/outputs do not satisfy declared contracts."""


class DependenciesError(SpliceError):
    """Raised when dependency policy cannot satisfy required modules."""


class WorkspaceNotFoundError(SpliceError):
    """Raised when no `.splice/` workspace can be located.

    Guidance: run `splice init` in your project root to create one.
    """
