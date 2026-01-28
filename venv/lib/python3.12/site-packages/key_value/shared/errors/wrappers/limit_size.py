from key_value.shared.errors.key_value import KeyValueOperationError


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
