from typing import Any

from key_value.shared.errors.base import BaseKeyValueError, ExtraInfoType


class KeyValueOperationError(BaseKeyValueError):
    """Base exception for all Key-Value operation errors."""


class SerializationError(KeyValueOperationError):
    """Raised when data cannot be serialized for storage."""


class DeserializationError(KeyValueOperationError):
    """Raised when stored data cannot be deserialized back to its original form."""


class MissingKeyError(KeyValueOperationError):
    """Raised when a key is missing from the store."""

    def __init__(self, operation: str, collection: str | None = None, key: str | None = None):
        super().__init__(
            message="A key was requested that was required but not found in the store.",
            extra_info={"operation": operation, "collection": collection or "default", "key": key},
        )


class InvalidTTLError(KeyValueOperationError):
    """Raised when a TTL is invalid."""

    def __init__(self, ttl: Any, extra_info: ExtraInfoType | None = None):
        super().__init__(
            message="A TTL is invalid.",
            extra_info={"ttl": str(ttl), **(extra_info or {})},
        )


class InvalidKeyError(KeyValueOperationError):
    """Raised when a key is invalid (e.g., uses reserved prefixes)."""


class ValueTooLargeError(KeyValueOperationError):
    """Raised when a value is too large."""

    def __init__(self, size: int, max_size: int, collection: str | None = None, key: str | None = None):
        super().__init__(
            message="Value size exceeds the maximum allowed size.",
            extra_info={"size": size, "max_size": max_size, "collection": collection or "default", "key": key},
        )
