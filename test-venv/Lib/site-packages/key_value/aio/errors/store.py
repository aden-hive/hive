"""Store-level error classes."""

from key_value.aio.errors.base import BaseKeyValueError


class KeyValueStoreError(BaseKeyValueError):
    """Base exception for all Key-Value store errors."""


class StoreSetupError(KeyValueStoreError):
    """Raised when a store setup fails."""


class StoreConnectionError(KeyValueStoreError):
    """Raised when unable to connect to or communicate with the underlying store."""


class PathSecurityError(KeyValueStoreError):
    """Raised when a path operation would violate security boundaries.

    This includes:
    - Path traversal attempts (e.g., using '../' to escape the data directory)
    - Symlink attacks (symlinks pointing outside the data directory)
    """
