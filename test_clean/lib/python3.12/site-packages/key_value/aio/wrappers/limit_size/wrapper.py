from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from key_value.shared.errors.wrappers.limit_size import EntryTooLargeError, EntryTooSmallError
from key_value.shared.utils.managed_entry import estimate_serialized_size
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


class LimitSizeWrapper(BaseWrapper):
    """Wrapper that limits the size of entries stored in the cache. When using a key_value store as a cache, you may want to prevent caching
    of very small or very large entries. This wrapper allows you to silently (or loudly) ignore entries that do not fall within the
    specified size limits.

    This wrapper checks the serialized size of values before storing them. This incurs a performance penalty
    as it requires JSON serialization of the value separate from serialization that occurs when the value is stored.

    This wrapper does not prevent returning objects (get, ttl, get_many, ttl_many) that exceed the size limit, just storing
    them (put, put_many).
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        *,
        min_size: int | None = None,
        max_size: int | None = None,
        raise_on_too_small: bool = False,
        raise_on_too_large: bool = True,
    ) -> None:
        """Initialize the limit size wrapper.

        Args:
            key_value: The store to wrap.
            min_size: The minimum size (in bytes) allowed for each entry. If None, no minimum size is enforced.
            max_size: The maximum size (in bytes) allowed for each entry. If None, no maximum size is enforced.
            raise_on_too_small: If True, raises EntryTooSmallError when an entry is less than min_size.
                                 If False (default), silently ignores entries that are too small.
            raise_on_too_large: If True (default), raises EntryTooLargeError when an entry exceeds max_size.
                                 If False, silently ignores entries that are too large.
        """
        self.key_value: AsyncKeyValue = key_value
        self.min_size: int | None = min_size
        self.max_size: int | None = max_size
        self.raise_on_too_small: bool = raise_on_too_small
        self.raise_on_too_large: bool = raise_on_too_large

        super().__init__()

    def _within_size_limit(self, value: dict[str, Any], *, collection: str | None = None, key: str | None = None) -> bool:
        """Check if a value exceeds the maximum size.

        Args:
            value: The value to check.
            collection: The collection name (for error messages).
            key: The key name (for error messages).

        Returns:
            True if the value is within the size limit, False otherwise.

        Raises:
            EntryTooSmallError: If raise_on_too_small is True and the value is less than min_size.
            EntryTooLargeError: If raise_on_too_large is True and the value exceeds max_size.
        """

        item_size: int = estimate_serialized_size(value=value)

        if self.min_size is not None and item_size < self.min_size:
            if self.raise_on_too_small:
                raise EntryTooSmallError(size=item_size, min_size=self.min_size, collection=collection, key=key)
            return False

        if self.max_size is not None and item_size > self.max_size:
            if self.raise_on_too_large:
                raise EntryTooLargeError(size=item_size, max_size=self.max_size, collection=collection, key=key)
            return False

        return True

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        if self._within_size_limit(value=dict(value), collection=collection, key=key):
            await self.key_value.put(collection=collection, key=key, value=value, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        filtered_keys: list[str] = []
        filtered_values: list[Mapping[str, Any]] = []

        for k, v in zip(keys, values, strict=True):
            if self._within_size_limit(value=dict(v), collection=collection, key=k):
                filtered_keys.append(k)
                filtered_values.append(v)

        if filtered_keys:
            await self.key_value.put_many(keys=filtered_keys, values=filtered_values, collection=collection, ttl=ttl)
