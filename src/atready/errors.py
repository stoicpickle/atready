"""AtReady error types with user-facing messages."""


class AtReadyError(Exception):
    """Base class for expected, user-actionable failures."""


class ConfigurationError(AtReadyError):
    """Raised when configuration input is unsafe or malformed."""


class StorageError(AtReadyError):
    """Raised when private local state cannot be created safely."""
