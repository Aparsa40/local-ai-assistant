"""Storage Manager public interface."""
from .config import StorageConfig
from .exceptions import StorageConfigurationError, StorageError, StorageUnavailableError
from .manager import StorageManager, get_storage_manager

__all__ = [
    "StorageConfig",
    "StorageError",
    "StorageConfigurationError",
    "StorageUnavailableError",
    "StorageManager",
    "get_storage_manager",
]
