import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal, SupportsFloat

from key_value.shared.constants import DEFAULT_COLLECTION_NAME
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper


class LoggingWrapper(BaseWrapper):
    """Wrapper that logs all operations for debugging and auditing.

    This wrapper logs all key-value operations including their parameters and results.
    It's useful for:
    - Debugging application behavior
    - Auditing data access
    - Understanding cache hit/miss patterns
    - Monitoring performance issues
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        logger: logging.Logger | None = None,
        log_level: int = logging.INFO,
        log_values: bool = False,
        structured_logs: bool = False,
    ) -> None:
        """Initialize the logging wrapper.

        Args:
            key_value: The store to wrap.
            logger: Logger instance to use. If None, creates a logger named 'key_value.logging'.
            log_level: Logging level to use. Defaults to logging.INFO.
            log_values: If True, logs the actual values being stored/retrieved.
                       If False (default), only logs metadata (keys, collections, operation types).
                       Set to False to avoid logging sensitive data.
            structured_logs: If True, logs the values as structured data.
                       If False (default), logs the values as a string.
        """
        self.key_value: AsyncKeyValue = key_value
        self.logger: logging.Logger = logger or logging.getLogger("key_value.logging")
        self.log_level: int = log_level
        self.log_values: bool = log_values
        self.structured_logs: bool = structured_logs

        super().__init__()

    def _format_collection(self, collection: str | None) -> str:
        """Format collection name for logging."""
        return collection or DEFAULT_COLLECTION_NAME

    def _format_message(
        self,
        state: Literal["start", "finish"],
        action: str,
        keys: Sequence[str] | str,
        collection: str | None,
        values: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        if self.structured_logs:
            structured_data: dict[str, Any] = {
                "status": state,
                "action": action,
                "collection": collection,
                "keys": keys,
            }
            if values is not None:
                structured_data["value"] = values

            if extra is not None:
                structured_data["extra"] = extra

            return json.dumps(structured_data)

        base_msg = f"{state.capitalize()} {action} collection='{self._format_collection(collection)}' keys='{keys}'"

        if values is not None:
            base_msg += f" value={values}"
        if extra is not None:
            base_msg += f" ({extra})"

        return base_msg

    def _log(
        self,
        state: Literal["start", "finish"],
        action: str,
        keys: Sequence[str] | str,
        collection: str | None,
        values: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.logger.log(
            self.log_level, self._format_message(state=state, action=action, keys=keys, collection=collection, values=values, extra=extra)
        )

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        self._log(state="start", action="GET", keys=key, collection=collection)

        result = await self.key_value.get(key=key, collection=collection)

        self._log(state="finish", action="GET", keys=key, collection=collection, values=result, extra={"hit": result is not None})

        return result

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        self._log(state="start", action="GET_MANY", keys=keys, collection=collection, extra={"keys": keys[:5]})

        results = await self.key_value.get_many(keys=keys, collection=collection)

        hits = sum(1 for r in results if r is not None)
        misses = len(results) - hits

        self._log(state="finish", action="GET_MANY", keys=keys, collection=collection, extra={"hits": hits, "misses": misses})

        return results

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        self._log(state="start", action="TTL", keys=key, collection=collection)

        value, ttl = await self.key_value.ttl(key=key, collection=collection)

        self._log(state="finish", action="TTL", keys=key, collection=collection, values=value, extra={"ttl": ttl})

        return value, ttl

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        self._log(state="start", action="TTL_MANY", keys=keys, collection=collection, extra={"keys": keys[:5]})

        results = await self.key_value.ttl_many(keys=keys, collection=collection)

        hits = sum(1 for r in results if r[0] is not None)
        misses = len(results) - hits

        self._log(state="finish", action="TTL_MANY", keys=keys, collection=collection, extra={"hits": hits, "misses": misses})

        return results

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        self._log(state="start", action="PUT", keys=key, collection=collection, values=value, extra={"ttl": ttl})

        await self.key_value.put(key=key, value=value, collection=collection, ttl=ttl)

        self._log(state="finish", action="PUT", keys=key, collection=collection, values=value, extra={"ttl": ttl})

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        self._log(state="start", action="PUT_MANY", keys=keys, collection=collection, values=values, extra={"ttl": ttl})

        await self.key_value.put_many(keys=keys, values=values, collection=collection, ttl=ttl)

        self._log(state="finish", action="PUT_MANY", keys=keys, collection=collection, values=values, extra={"ttl": ttl})

    @override
    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        self._log(state="start", action="DELETE", keys=key, collection=collection)

        result: bool = await self.key_value.delete(key=key, collection=collection)

        self._log(state="finish", action="DELETE", keys=key, collection=collection, extra={"deleted": result})
        return result

    @override
    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        self._log(state="start", action="DELETE_MANY", keys=keys, collection=collection, extra={"keys": keys[:5]})

        deleted_count: int = await self.key_value.delete_many(keys=keys, collection=collection)

        self._log(state="finish", action="DELETE_MANY", keys=keys, collection=collection, extra={"deleted": deleted_count})

        return deleted_count
