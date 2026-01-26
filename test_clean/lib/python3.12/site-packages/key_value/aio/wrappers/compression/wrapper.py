import base64
import gzip
import json
from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

from key_value.shared.utils.managed_entry import estimate_serialized_size
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper

# Special keys used to store compressed data
_COMPRESSED_DATA_KEY = "__compressed_data__"
_COMPRESSION_VERSION_KEY = "__compression_version__"
_COMPRESSION_VERSION = 1
_COMPRESSION_ALGORITHM_KEY = "__compression_algorithm__"


class CompressionWrapper(BaseWrapper):
    """Wrapper that compresses values before storing and decompresses on retrieval.

    This wrapper compresses the JSON-serialized value using the specified compression algorithm and stores it as a
    base64-encoded string within a special key in the dictionary. This allows compression
    while maintaining the dict[str, Any] interface.

    The compressed format looks like:
    {
        "__compressed_data__": "base64-encoded-compressed-data",
        "__compression_algorithm__": "gzip",
        "__compression_version__": 1
    }
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        min_size_to_compress: int = 1024,
    ) -> None:
        """Initialize the compression wrapper.

        Args:
            key_value: The store to wrap.
            min_size_to_compress: Only compress values larger than this many bytes.
                                 Defaults to 1024 bytes (1KB).
        """
        self.key_value: AsyncKeyValue = key_value
        self.min_size_to_compress: int = min_size_to_compress

        super().__init__()

    def _should_compress(self, value: dict[str, Any]) -> bool:
        """Determine if a value should be compressed based on its size."""
        # Don't compress if it's already compressed
        if _COMPRESSED_DATA_KEY in value:
            return False

        # Check size
        item_size: int = estimate_serialized_size(value=value)
        return item_size >= self.min_size_to_compress

    def _compress_value(self, value: dict[str, Any]) -> dict[str, Any]:
        """Compress a value into the compressed format."""
        if not self._should_compress(value):
            return value

        # Serialize to JSON
        json_str = json.dumps(value, separators=(",", ":"))
        json_bytes = json_str.encode("utf-8")

        # Compress with gzip
        compressed_bytes = gzip.compress(json_bytes, compresslevel=1)

        # Encode to base64 for storage in dict
        base64_str = base64.b64encode(compressed_bytes).decode("ascii")

        return {
            _COMPRESSED_DATA_KEY: base64_str,
            _COMPRESSION_VERSION_KEY: _COMPRESSION_VERSION,
            _COMPRESSION_ALGORITHM_KEY: "gzip",
        }

    def _decompress_value(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Decompress a value from the compressed format."""
        if value is None:
            return None

        # Check if it's compressed
        if _COMPRESSED_DATA_KEY not in value:
            return value

        # Extract compressed data
        base64_str = value[_COMPRESSED_DATA_KEY]
        if not isinstance(base64_str, str):
            # Corrupted data, return as-is
            return value

        try:
            # Decode from base64
            compressed_bytes = base64.b64decode(base64_str)

            # Decompress with gzip
            json_bytes = gzip.decompress(compressed_bytes)

            # Parse JSON
            json_str = json_bytes.decode("utf-8")
            return json.loads(json_str)  # type: ignore[no-any-return]
        except Exception:
            # If decompression fails, return the original value
            # This handles cases where data might be corrupted
            return value

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        value = await self.key_value.get(key=key, collection=collection)
        return self._decompress_value(value)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        values = await self.key_value.get_many(keys=keys, collection=collection)
        return [self._decompress_value(value) for value in values]

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        value, ttl = await self.key_value.ttl(key=key, collection=collection)
        return self._decompress_value(value), ttl

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        results = await self.key_value.ttl_many(keys=keys, collection=collection)
        return [(self._decompress_value(value), ttl) for value, ttl in results]

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        compressed_value = self._compress_value(dict(value))
        return await self.key_value.put(key=key, value=compressed_value, collection=collection, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        compressed_values = [self._compress_value(dict(value)) for value in values]
        return await self.key_value.put_many(keys=keys, values=compressed_values, collection=collection, ttl=ttl)
