from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from key_value.shared.errors.wrappers.read_only import ReadOnlyError
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


class ReadOnlyWrapper(BaseWrapper):
    """Wrapper that prevents all write operations on the underlying store.

    This wrapper allows all read operations (get, get_many, ttl, ttl_many) to pass through
    normally, but blocks all write operations (put, put_many, delete, delete_many).
    This is useful for:
    - Protecting production data during testing
    - Enforcing read-only access to read replicas
    - Preventing accidental modifications in certain environments
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        raise_on_write: bool = True,
    ) -> None:
        """Initialize the read-only wrapper.

        Args:
            key_value: The store to wrap.
            raise_on_write: If True (default), raises ReadOnlyError on write attempts.
                           If False, silently ignores writes (put/put_many return None,
                           delete/delete_many return False/0).
        """
        self.key_value: AsyncKeyValue = key_value
        self.raise_on_write: bool = raise_on_write

        super().__init__()

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        return await self.key_value.get(key=key, collection=collection)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        return await self.key_value.get_many(keys=keys, collection=collection)

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        return await self.key_value.ttl(key=key, collection=collection)

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        return await self.key_value.ttl_many(keys=keys, collection=collection)

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        if self.raise_on_write:
            raise ReadOnlyError(operation="put", collection=collection, key=key)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        if self.raise_on_write:
            raise ReadOnlyError(operation="put_many", collection=collection, key=f"{len(keys)} keys")

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        if self.raise_on_write:
            raise ReadOnlyError(operation="delete", collection=collection, key=key)
        return False

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        if self.raise_on_write:
            raise ReadOnlyError(operation="delete_many", collection=collection, key=f"{len(keys)} keys")
        return 0
