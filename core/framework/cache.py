"""
High-Performance Caching Layer

Multi-level caching with:
- L1: In-memory LRU cache (fast, process-local)
- L2: Redis cache (shared across workers)
- Intelligent key generation
- Automatic TTL management
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

import orjson
from cachetools import LRUCache, TTLCache

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheStats:
    """Cache performance statistics."""
    l1_hits: int = 0
    l1_misses: int = 0
    l2_hits: int = 0
    l2_misses: int = 0
    writes: int = 0
    
    @property
    def l1_hit_rate(self) -> float:
        total = self.l1_hits + self.l1_misses
        return self.l1_hits / total if total > 0 else 0.0
    
    @property
    def l2_hit_rate(self) -> float:
        total = self.l2_hits + self.l2_misses
        return self.l2_hits / total if total > 0 else 0.0
    
    @property
    def overall_hit_rate(self) -> float:
        total_hits = self.l1_hits + self.l2_hits
        total = total_hits + self.l2_misses  # L2 miss = total miss
        return total_hits / total if total > 0 else 0.0


class AgentCache:
    """
    High-performance multi-level caching for agent operations.
    
    Features:
    - L1 (memory): Fast LRU cache with TTL
    - L2 (Redis): Shared cache across workers
    - Automatic serialization with orjson
    - Cache key generation utilities
    - Statistics tracking
    
    Usage:
        cache = AgentCache(redis_url="redis://localhost:6379")
        await cache.initialize()
        
        # Get/Set
        await cache.set("my_key", {"data": "value"}, ttl=300)
        data = await cache.get("my_key")
        
        # Decorator for caching function results
        @cache.cached(ttl=3600)
        async def expensive_operation(param1, param2):
            ...
    """
    
    def __init__(
        self,
        l1_maxsize: int = 1000,
        l1_ttl: int = 300,  # 5 minutes
        redis_url: Optional[str] = None,
        key_prefix: str = "agent:",
    ):
        self.l1_maxsize = l1_maxsize
        self.l1_ttl = l1_ttl
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        
        # L1: In-memory TTL cache
        self._l1_cache: TTLCache = TTLCache(maxsize=l1_maxsize, ttl=l1_ttl)
        self._l1_lock = asyncio.Lock()
        
        # L2: Redis (optional)
        self._redis = None
        self._redis_pool = None
        
        # Statistics
        self.stats = CacheStats()
    
    async def initialize(self) -> None:
        """Initialize Redis connection if URL provided."""
        if self.redis_url:
            try:
                import redis.asyncio as redis
                
                self._redis_pool = redis.ConnectionPool.from_url(
                    self.redis_url,
                    max_connections=20,
                    decode_responses=False,
                )
                self._redis = redis.Redis(connection_pool=self._redis_pool)
                logger.info(f"Cache connected to Redis: {self.redis_url}")
            except ImportError:
                logger.warning("Redis not available, using L1 cache only")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}, using L1 cache only")
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Checks L1 first, then L2 (Redis). Promotes L2 hits to L1.
        """
        full_key = f"{self.key_prefix}{key}"
        
        # Check L1 (memory)
        async with self._l1_lock:
            if full_key in self._l1_cache:
                self.stats.l1_hits += 1
                return self._l1_cache[full_key]
            self.stats.l1_misses += 1
        
        # Check L2 (Redis)
        if self._redis:
            try:
                data = await self._redis.get(full_key)
                if data:
                    self.stats.l2_hits += 1
                    value = orjson.loads(data)
                    
                    # Promote to L1
                    async with self._l1_lock:
                        self._l1_cache[full_key] = value
                    
                    return value
                self.stats.l2_misses += 1
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
                self.stats.l2_misses += 1
        
        return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """
        Set value in cache.
        
        Writes to both L1 and L2 for consistency.
        """
        full_key = f"{self.key_prefix}{key}"
        ttl = ttl or self.l1_ttl
        
        # Write to L1
        async with self._l1_lock:
            self._l1_cache[full_key] = value
        
        # Write to L2 (Redis)
        if self._redis:
            try:
                data = orjson.dumps(value)
                await self._redis.set(full_key, data, ex=ttl)
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
        
        self.stats.writes += 1
    
    async def delete(self, key: str) -> None:
        """Delete value from both cache levels."""
        full_key = f"{self.key_prefix}{key}"
        
        # Delete from L1
        async with self._l1_lock:
            self._l1_cache.pop(full_key, None)
        
        # Delete from L2
        if self._redis:
            try:
                await self._redis.delete(full_key)
            except Exception as e:
                logger.warning(f"Redis delete error: {e}")
    
    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._l1_lock:
            self._l1_cache.clear()
        
        if self._redis:
            try:
                # Clear only our prefixed keys
                async for key in self._redis.scan_iter(f"{self.key_prefix}*"):
                    await self._redis.delete(key)
            except Exception as e:
                logger.warning(f"Redis clear error: {e}")
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
        if self._redis_pool:
            await self._redis_pool.disconnect()
            self._redis_pool = None
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "l1_hits": self.stats.l1_hits,
            "l1_misses": self.stats.l1_misses,
            "l1_hit_rate": f"{self.stats.l1_hit_rate:.2%}",
            "l2_hits": self.stats.l2_hits,
            "l2_misses": self.stats.l2_misses,
            "l2_hit_rate": f"{self.stats.l2_hit_rate:.2%}",
            "overall_hit_rate": f"{self.stats.overall_hit_rate:.2%}",
            "writes": self.stats.writes,
            "l1_size": len(self._l1_cache),
            "l1_maxsize": self.l1_maxsize,
        }
    
    # === Cache Key Utilities ===
    
    @staticmethod
    def make_key(*args, **kwargs) -> str:
        """
        Create deterministic cache key from arguments.
        
        Uses MD5 hash for consistent key generation across processes.
        """
        # Sort kwargs for deterministic ordering
        content = orjson.dumps({
            "args": args,
            "kwargs": dict(sorted(kwargs.items())),
        })
        return hashlib.md5(content).hexdigest()
    
    @staticmethod
    def make_llm_key(
        messages: list[dict],
        system: str = "",
        model: str = "",
        **kwargs,
    ) -> str:
        """
        Create cache key for LLM calls.
        
        Specifically designed for caching LLM responses.
        """
        content = orjson.dumps({
            "messages": messages,
            "system": system,
            "model": model,
            "kwargs": dict(sorted(kwargs.items())),
        })
        return f"llm:{hashlib.md5(content).hexdigest()}"
    
    # === Decorator for Caching ===
    
    def cached(
        self,
        ttl: Optional[int] = None,
        key_func: Optional[Callable[..., str]] = None,
    ):
        """
        Decorator for caching async function results.
        
        Usage:
            cache = AgentCache()
            
            @cache.cached(ttl=3600)
            async def expensive_operation(param1, param2):
                ...
        """
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            async def wrapper(*args, **kwargs) -> T:
                # Generate cache key
                if key_func:
                    key = key_func(*args, **kwargs)
                else:
                    key = f"{func.__name__}:{self.make_key(*args, **kwargs)}"
                
                # Try cache first
                cached_value = await self.get(key)
                if cached_value is not None:
                    return cached_value
                
                # Call function
                result = await func(*args, **kwargs)
                
                # Cache result
                await self.set(key, result, ttl=ttl)
                
                return result
            
            return wrapper
        return decorator


class CachedLLMProvider:
    """
    LLM provider wrapper with automatic caching.
    
    Caches identical LLM calls to save costs and reduce latency.
    
    Usage:
        from framework.llm.litellm import LiteLLMProvider
        
        base_provider = LiteLLMProvider(model="claude-3-5-sonnet")
        cache = AgentCache(redis_url="redis://localhost")
        
        cached_provider = CachedLLMProvider(base_provider, cache)
        response = await cached_provider.complete(messages, system)
    """
    
    def __init__(
        self,
        provider: Any,  # LLMProvider
        cache: AgentCache,
        cache_ttl: int = 3600,  # 1 hour
    ):
        self.provider = provider
        self.cache = cache
        self.cache_ttl = cache_ttl
    
    async def complete(
        self,
        messages: list[dict],
        system: str = "",
        **kwargs,
    ):
        """Complete with caching."""
        # Generate cache key
        model = getattr(self.provider, "model", "default")
        cache_key = AgentCache.make_llm_key(
            messages=messages,
            system=system,
            model=model,
            **kwargs,
        )
        
        # Check cache
        cached = await self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"LLM cache hit: {cache_key[:16]}...")
            # Reconstruct LLMResponse
            from framework.llm.provider import LLMResponse
            return LLMResponse(**cached)
        
        # Call provider
        if asyncio.iscoroutinefunction(self.provider.complete):
            response = await self.provider.complete(messages, system, **kwargs)
        else:
            response = self.provider.complete(messages, system, **kwargs)
        
        # Cache successful responses
        if response and response.content:
            await self.cache.set(cache_key, {
                "content": response.content,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "stop_reason": response.stop_reason,
            }, ttl=self.cache_ttl)
        
        return response
    
    async def complete_with_tools(
        self,
        messages: list[dict],
        system: str,
        tools: list,
        tool_executor: Callable,
        **kwargs,
    ):
        """
        Complete with tools (not cached - tool calls have side effects).
        """
        if asyncio.iscoroutinefunction(self.provider.complete_with_tools):
            return await self.provider.complete_with_tools(
                messages, system, tools, tool_executor, **kwargs
            )
        return self.provider.complete_with_tools(
            messages, system, tools, tool_executor, **kwargs
        )


# === Singleton Cache Instance ===

_global_cache: Optional[AgentCache] = None


async def get_cache(
    redis_url: Optional[str] = None,
    **kwargs,
) -> AgentCache:
    """
    Get or create global cache instance.
    
    Usage:
        cache = await get_cache(redis_url="redis://localhost")
        await cache.set("key", "value")
    """
    global _global_cache
    
    if _global_cache is None:
        _global_cache = AgentCache(redis_url=redis_url, **kwargs)
        await _global_cache.initialize()
    
    return _global_cache


async def close_cache() -> None:
    """Close global cache instance."""
    global _global_cache
    
    if _global_cache:
        await _global_cache.close()
        _global_cache = None
