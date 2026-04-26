"""AWS S3-based key-value store."""

from key_value.aio.stores.s3.store import (
    S3CollectionSanitizationStrategy,
    S3KeySanitizationStrategy,
    S3Store,
)

__all__ = [
    "S3CollectionSanitizationStrategy",
    "S3KeySanitizationStrategy",
    "S3Store",
]
