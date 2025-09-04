class SpliceError(Exception):
    """Base class for Splice exceptions."""


class ConfigError(SpliceError):
    """Raised when the global config is invalid."""


class SpecError(SpliceError):
    """Raised when a function spec is invalid or missing."""


class SpecNotFoundError(SpecError):
    """Raised when a function spec YAML cannot be found in the expected location."""


class ExecutionError(SpliceError):
    """Raised when executing generated code fails."""


class SandboxViolation(SpliceError):
    """Raised when generated code attempts a disallowed operation in the sandbox."""


class ValidationError(SpliceError):
    """Raised when inputs/outputs do not satisfy declared contracts."""


class DependenciesError(SpliceError):
    """Raised when dependency policy cannot satisfy required modules."""


