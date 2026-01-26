from key_value.shared.errors.key_value import KeyValueOperationError


class ReadOnlyError(KeyValueOperationError):
    """Raised when a write operation is attempted on a read-only store."""

    def __init__(self, operation: str, collection: str | None = None, key: str | None = None):
        super().__init__(
            message="Write operation not allowed on read-only store.",
            extra_info={"operation": operation, "collection": collection or "default", "key": key or "N/A"},
        )
