"""Wrapper-specific error classes for encryption, read-only, and size limiting."""

from key_value.aio.errors.key_value import KeyValueOperationError


class EncryptionError(KeyValueOperationError):
    """Exception raised when encryption or decryption fails."""


class DecryptionError(EncryptionError):
    """Exception raised when decryption fails."""


class EncryptionVersionError(EncryptionError):
    """Exception raised when the encryption version is not supported."""


class CorruptedDataError(DecryptionError):
    """Exception raised when the encrypted data is corrupted."""


class ReadOnlyError(KeyValueOperationError):
    """Raised when a write operation is attempted on a read-only store."""

    def __init__(self, operation: str, collection: str | None = None, key: str | None = None):
        super().__init__(
            message="Write operation not allowed on read-only store.",
            extra_info={"operation": operation, "collection": collection or "default", "key": key or "N/A"},
        )


class EntryTooLargeError(KeyValueOperationError):
    """Raised when an entry exceeds the maximum allowed size."""

    def __init__(self, size: int, max_size: int, collection: str | None = None, key: str | None = None):
        super().__init__(
            message="Entry size exceeds the maximum allowed size.",
            extra_info={"size": size, "max_size": max_size, "collection": collection or "default", "key": key},
        )


class EntryTooSmallError(KeyValueOperationError):
    """Raised when an entry is less than the minimum allowed size."""

    def __init__(self, size: int, min_size: int, collection: str | None = None, key: str | None = None):
        super().__init__(
            message="Entry size is less than the minimum allowed size.",
            extra_info={"size": size, "min_size": min_size, "collection": collection or "default", "key": key},
        )
