from key_value.shared.errors.base import BaseKeyValueError


class KeyValueStoreError(BaseKeyValueError):
    """Base exception for all Key-Value store errors."""


class StoreSetupError(KeyValueStoreError):
    """Raised when a store setup fails."""


class StoreConnectionError(KeyValueStoreError):
    """Raised when unable to connect to or communicate with the underlying store."""
