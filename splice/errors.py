class SpliceError(Exception):
    """Base class for Splice exceptions."""


class ConfigError(SpliceError):
    """Raised when the global config is invalid."""


class SpecError(SpliceError):
    """Raised when a function spec is invalid or missing."""


class ExecutionError(SpliceError):
    """Raised when executing generated code fails."""


class SandboxViolation(SpliceError):
    """Raised when generated code attempts a disallowed operation in the sandbox."""


