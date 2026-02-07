"""Multi-tier caching layer for the Hive framework.

Provides caching for:
- LLM responses (semantic caching)
- Tool results
- Computed embeddings
- General key-value storage

Supports:
- L1: In-memory LRU cache (fast, limited size)
- L2: Optional Redis backend (persistent, distributed)

Usage:
    from framework.cache import Cache, get_cache

    cache = get_cache()

    # Simple key-value
    await cache.set("key", value, ttl=3600)
    value = await cache.get("key")

    # LLM response caching
    response = await cache.get_or_compute(
        key=cache.llm_key(model, messages),
        compute_fn=lambda: llm.complete(messages),
        ttl=3600,
    )
"""

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CacheBackend(StrEnum):
    """Cache backend types."""

    MEMORY = "memory"
    REDIS = "redis"


@dataclass
class CacheConfig:
    """Cache configuration."""

    # Memory cache settings
    memory_max_size: int = 1000
    memory_max_bytes: int = 100 * 1024 * 1024  # 100MB

    # Default TTL (seconds)
    default_ttl: int = 3600  # 1 hour
    llm_response_ttl: int = 86400  # 24 hours
    tool_result_ttl: int = 300  # 5 minutes

    # Redis settings (optional)
    redis_url: str | None = None
    redis_prefix: str = "hive:"

    # Serialization
    compress_threshold: int = 1024  # Compress values > 1KB


@dataclass
class CacheEntry:
    """A cached value with metadata."""

    value: Any
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    hits: int = 0
    size_bytes: int = 0

    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def age(self) -> float:
        """Age in seconds."""
        return time.time() - self.created_at


class LRUCache:
    """Thread-safe LRU cache with size limits.

    Evicts least recently used items when capacity is exceeded.
    """

    def __init__(self, max_size: int = 1000, max_bytes: int = 100 * 1024 * 1024):
        self.max_size = max_size
        self.max_bytes = max_bytes
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._current_bytes = 0
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    async def get(self, key: str) -> CacheEntry | None:
        """Get entry and move to end (most recently used)."""
        async with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                return None

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired:
                self._remove_entry(key)
                self._stats["misses"] += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hits += 1
            self._stats["hits"] += 1
            return entry

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Set entry with optional TTL."""
        # Calculate size
        try:
            size_bytes = len(json.dumps(value, default=str).encode())
        except Exception:
            size_bytes = 1024  # Default estimate

        entry = CacheEntry(
            value=value,
            expires_at=time.time() + ttl if ttl else None,
            size_bytes=size_bytes,
        )

        async with self._lock:
            # Remove existing entry if present
            if key in self._cache:
                self._remove_entry(key)

            # Evict until we have space
            while (
                len(self._cache) >= self.max_size
                or self._current_bytes + size_bytes > self.max_bytes
            ):
                if not self._cache:
                    break
                self._evict_oldest()

            # Add new entry
            self._cache[key] = entry
            self._current_bytes += size_bytes

    async def delete(self, key: str) -> bool:
        """Delete entry by key."""
        async with self._lock:
            if key in self._cache:
                self._remove_entry(key)
                return True
            return False

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._cache.clear()
            self._current_bytes = 0

    def _remove_entry(self, key: str) -> None:
        """Remove entry without lock (internal use)."""
        if key in self._cache:
            self._current_bytes -= self._cache[key].size_bytes
            del self._cache[key]

    def _evict_oldest(self) -> None:
        """Evict oldest (least recently used) entry."""
        if self._cache:
            oldest_key = next(iter(self._cache))
            self._remove_entry(oldest_key)
            self._stats["evictions"] += 1

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "bytes": self._current_bytes,
            "max_size": self.max_size,
            "max_bytes": self.max_bytes,
            **self._stats,
            "hit_rate": (
                self._stats["hits"] / (self._stats["hits"] + self._stats["misses"])
                if (self._stats["hits"] + self._stats["misses"]) > 0
                else 0.0
            ),
        }


class RedisBackend:
    """Redis cache backend for distributed caching."""

    def __init__(self, url: str, prefix: str = "hive:"):
        self.url = url
        self.prefix = prefix
        self._client = None

    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            import redis.asyncio as redis

            self._client = redis.from_url(self.url)
            await self._client.ping()
            logger.info(f"Connected to Redis at {self.url}")
        except ImportError:
            raise ImportError("redis package not installed. Run: pip install redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None

    def _key(self, key: str) -> str:
        """Add prefix to key."""
        return f"{self.prefix}{key}"

    async def get(self, key: str) -> Any | None:
        """Get value from Redis."""
        if not self._client:
            return None

        try:
            data = await self._client.get(self._key(key))
            if data is None:
                return None

            # Decompress if needed
            if data.startswith(b"\x1f\x8b"):  # Gzip magic bytes
                import gzip

                data = gzip.decompress(data)

            return json.loads(data)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        compress: bool = False,
    ) -> None:
        """Set value in Redis."""
        if not self._client:
            return

        try:
            data = json.dumps(value, default=str).encode()

            # Compress large values
            if compress and len(data) > 1024:
                import gzip

                data = gzip.compress(data)

            if ttl:
                await self._client.setex(self._key(key), ttl, data)
            else:
                await self._client.set(self._key(key), data)
        except Exception as e:
            logger.warning(f"Redis set error: {e}")

    async def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        if not self._client:
            return False

        try:
            result = await self._client.delete(self._key(key))
            return result > 0
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        if not self._client:
            return 0

        try:
            keys = []
            async for key in self._client.scan_iter(match=self._key(pattern)):
                keys.append(key)

            if keys:
                return await self._client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Redis clear pattern error: {e}")
            return 0


class Cache:
    """Multi-tier cache with L1 memory and optional L2 Redis.

    Provides semantic caching for LLM responses and general
    key-value storage with TTL support.
    """

    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig()
        self._l1 = LRUCache(
            max_size=self.config.memory_max_size,
            max_bytes=self.config.memory_max_bytes,
        )
        self._l2: RedisBackend | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize cache backends."""
        if self._initialized:
            return

        # Initialize Redis if configured
        if self.config.redis_url:
            self._l2 = RedisBackend(
                url=self.config.redis_url,
                prefix=self.config.redis_prefix,
            )
            await self._l2.connect()

        self._initialized = True
        logger.info("Cache initialized")

    async def close(self) -> None:
        """Close cache backends."""
        if self._l2:
            await self._l2.disconnect()
        await self._l1.clear()
        self._initialized = False

    async def get(self, key: str) -> Any | None:
        """Get value from cache (checks L1 then L2)."""
        # Check L1 first
        entry = await self._l1.get(key)
        if entry is not None:
            return entry.value

        # Check L2 if available
        if self._l2:
            value = await self._l2.get(key)
            if value is not None:
                # Promote to L1
                await self._l1.set(key, value, ttl=self.config.default_ttl)
                return value

        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Set value in cache (writes to L1 and L2)."""
        ttl = ttl or self.config.default_ttl

        # Write to L1
        await self._l1.set(key, value, ttl=ttl)

        # Write to L2 if available
        if self._l2:
            compress = (
                len(json.dumps(value, default=str)) > self.config.compress_threshold
            )
            await self._l2.set(key, value, ttl=ttl, compress=compress)

    async def delete(self, key: str) -> None:
        """Delete from all cache tiers."""
        await self._l1.delete(key)
        if self._l2:
            await self._l2.delete(key)

    async def get_or_compute(
        self,
        key: str,
        compute_fn: Callable[[], T],
        ttl: int | None = None,
    ) -> T:
        """Get from cache or compute and store.

        This is the primary pattern for caching expensive operations.

        Args:
            key: Cache key
            compute_fn: Async function to compute value if not cached
            ttl: Time to live in seconds

        Returns:
            Cached or computed value
        """
        # Try cache first
        cached = await self.get(key)
        if cached is not None:
            return cached

        # Compute value
        if asyncio.iscoroutinefunction(compute_fn):
            value = await compute_fn()
        else:
            value = compute_fn()

        # Cache result
        await self.set(key, value, ttl=ttl)
        return value

    # Key generation helpers

    @staticmethod
    def llm_key(model: str, messages: list[dict], **kwargs) -> str:
        """Generate cache key for LLM request.

        Creates a deterministic hash of the request parameters.
        """
        key_data = {
            "model": model,
            "messages": messages,
            **kwargs,
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        hash_value = hashlib.sha256(key_str.encode()).hexdigest()[:32]
        return f"llm:{model}:{hash_value}"

    @staticmethod
    def tool_key(tool_name: str, inputs: dict) -> str:
        """Generate cache key for tool execution."""
        key_data = {"tool": tool_name, "inputs": inputs}
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        hash_value = hashlib.sha256(key_str.encode()).hexdigest()[:32]
        return f"tool:{tool_name}:{hash_value}"

    @staticmethod
    def embedding_key(model: str, text: str) -> str:
        """Generate cache key for embedding."""
        hash_value = hashlib.sha256(text.encode()).hexdigest()[:32]
        return f"embed:{model}:{hash_value}"

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "l1": self._l1.stats(),
            "l2_enabled": self._l2 is not None,
        }


# Global cache instance
_global_cache: Cache | None = None
_cache_lock = asyncio.Lock()


async def get_cache(config: CacheConfig | None = None) -> Cache:
    """Get or create the global cache instance."""
    global _global_cache

    if _global_cache is None:
        async with _cache_lock:
            if _global_cache is None:
                _global_cache = Cache(config)
                await _global_cache.initialize()

    return _global_cache


async def close_cache() -> None:
    """Close the global cache."""
    global _global_cache

    if _global_cache is not None:
        await _global_cache.close()
        _global_cache = None


__all__ = [
    "Cache",
    "CacheConfig",
    "CacheEntry",
    "CacheBackend",
    "LRUCache",
    "RedisBackend",
    "get_cache",
    "close_cache",
]
