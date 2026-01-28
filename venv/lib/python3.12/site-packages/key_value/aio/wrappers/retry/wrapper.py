from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat, TypeVar

from key_value.shared.code_gen.run import async_retry_operation
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper

T = TypeVar("T")


class RetryWrapper(BaseWrapper):
    """Wrapper that retries failed operations with exponential backoff.

    This wrapper automatically retries operations that fail with specified exceptions,
    using exponential backoff between attempts. This is useful for handling transient
    failures like network issues or temporary service unavailability.
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        max_retries: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
        retry_on: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
    ) -> None:
        """Initialize the retry wrapper.

        Args:
            key_value: The store to wrap.
            max_retries: Maximum number of retry attempts. Defaults to 3.
            initial_delay: Initial delay in seconds before first retry. Defaults to 0.1.
            max_delay: Maximum delay in seconds between retries. Defaults to 10.0.
            exponential_base: Base for exponential backoff calculation. Defaults to 2.0.
            retry_on: Tuple of exception types to retry on. Defaults to (ConnectionError, TimeoutError).
        """
        self.key_value: AsyncKeyValue = key_value
        self.max_retries: int = max_retries
        self.initial_delay: float = initial_delay
        self.max_delay: float = max_delay
        self.exponential_base: float = exponential_base
        self.retry_on: tuple[type[Exception], ...] = retry_on

        super().__init__()

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate the delay for a given attempt using exponential backoff."""
        delay = self.initial_delay * (self.exponential_base**attempt)
        return min(delay, self.max_delay)

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.get,
            key=key,
            collection=collection,
        )

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.get_many,
            keys=keys,
            collection=collection,
        )

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.ttl,
            key=key,
            collection=collection,
        )

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.ttl_many,
            keys=keys,
            collection=collection,
        )

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.put,
            key=key,
            value=value,
            collection=collection,
            ttl=ttl,
        )

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.put_many,
            keys=keys,
            values=values,
            collection=collection,
            ttl=ttl,
        )

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.delete,
            key=key,
            collection=collection,
        )

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        return await async_retry_operation(
            max_retries=self.max_retries,
            retry_on=self.retry_on,
            initial_delay=self.initial_delay,
            max_delay=self.max_delay,
            exponential_base=self.exponential_base,
            operation=self.key_value.delete_many,
            keys=keys,
            collection=collection,
        )
