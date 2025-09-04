class SpliceError(Exception):
    """Base class for Splice exceptions."""


class ConfigError(SpliceError):
    """Raised when the global config is invalid."""


class SpecError(SpliceError):
    """Raised when a function spec is invalid or missing."""


