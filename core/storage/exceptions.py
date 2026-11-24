"""Storage-layer exceptions exposed without leaking backend-specific errors."""


class StorageError(RuntimeError):
    """Base exception for persistence failures."""


class StorageConfigurationError(StorageError, ValueError):
    """Raised when storage configuration is invalid or unsupported."""


class StorageUnavailableError(StorageError):
    """Raised when the configured storage backend cannot be reached."""
