"""LLM Connection Pool for efficient client management.

Provides connection pooling for LLM providers to:
- Reuse HTTP connections across requests
- Manage client lifecycle efficiently
- Implement health checks and automatic recovery
- Support concurrent requests with connection limits

Usage:
    from framework.llm.pool import ConnectionPool, get_pool

    # Get the global pool
    pool = get_pool()

    # Acquire a client for requests
    async with pool.acquire("anthropic") as client:
        response = await client.complete(...)

    # Or use the convenience method
    response = await pool.execute("anthropic", "complete", messages=[...])
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class PoolStatus(StrEnum):
    """Connection pool status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class PoolConfig:
    """Configuration for connection pool."""

    # Pool sizing
    min_connections: int = 1
    max_connections: int = 10

    # Timeouts (seconds)
    acquire_timeout: float = 30.0
    idle_timeout: float = 300.0  # 5 minutes
    health_check_interval: float = 60.0

    # Retry behavior
    max_retries: int = 3
    retry_delay: float = 1.0

    # Per-provider overrides
    provider_configs: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class PooledConnection:
    """A pooled connection wrapper."""

    provider: str
    client: Any
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    request_count: int = 0
    error_count: int = 0
    in_use: bool = False

    @property
    def age(self) -> float:
        """Age of connection in seconds."""
        return time.time() - self.created_at

    @property
    def idle_time(self) -> float:
        """Time since last use in seconds."""
        return time.time() - self.last_used

    def mark_used(self) -> None:
        """Mark connection as recently used."""
        self.last_used = time.time()
        self.request_count += 1

    def mark_error(self) -> None:
        """Record an error on this connection."""
        self.error_count += 1


class ConnectionPool:
    """Async connection pool for LLM providers.

    Manages a pool of reusable connections per provider,
    with automatic health checks and connection recycling.

    Example:
        pool = ConnectionPool(config)
        await pool.start()

        async with pool.acquire("anthropic") as client:
            response = await client.messages.create(...)

        await pool.stop()
    """

    def __init__(self, config: PoolConfig | None = None):
        self.config = config or PoolConfig()
        self._pools: dict[str, list[PooledConnection]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._running = False
        self._health_task: asyncio.Task | None = None
        self._stats: dict[str, dict[str, int]] = {}

    async def start(self) -> None:
        """Start the connection pool and health check task."""
        if self._running:
            return

        self._running = True
        self._health_task = asyncio.create_task(self._health_check_loop())
        logger.info("Connection pool started")

    async def stop(self) -> None:
        """Stop the connection pool and close all connections."""
        self._running = False

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Close all connections
        for provider, connections in self._pools.items():
            for conn in connections:
                await self._close_connection(conn)
            logger.info(f"Closed {len(connections)} connections for {provider}")

        self._pools.clear()
        logger.info("Connection pool stopped")

    def _get_lock(self, provider: str) -> asyncio.Lock:
        """Get or create lock for provider."""
        if provider not in self._locks:
            self._locks[provider] = asyncio.Lock()
        return self._locks[provider]

    def _get_semaphore(self, provider: str) -> asyncio.Semaphore:
        """Get or create semaphore for provider connection limit."""
        if provider not in self._semaphores:
            max_conn = self.config.provider_configs.get(provider, {}).get(
                "max_connections", self.config.max_connections
            )
            self._semaphores[provider] = asyncio.Semaphore(max_conn)
        return self._semaphores[provider]

    def _init_stats(self, provider: str) -> None:
        """Initialize stats for provider."""
        if provider not in self._stats:
            self._stats[provider] = {
                "acquired": 0,
                "released": 0,
                "created": 0,
                "closed": 0,
                "errors": 0,
                "timeouts": 0,
            }

    async def _create_connection(self, provider: str) -> PooledConnection:
        """Create a new connection for the given provider."""
        self._init_stats(provider)

        # Create appropriate client based on provider
        client = await self._create_client(provider)

        conn = PooledConnection(provider=provider, client=client)
        self._stats[provider]["created"] += 1

        logger.debug(f"Created new connection for {provider}")
        return conn

    async def _create_client(self, provider: str) -> Any:
        """Create a client instance for the provider.

        Override this method to customize client creation.
        """
        import os

        if provider == "anthropic":
            try:
                import anthropic

                return anthropic.AsyncAnthropic(
                    api_key=os.environ.get("ANTHROPIC_API_KEY"),
                )
            except ImportError:
                raise ImportError("anthropic package not installed")

        elif provider == "openai":
            try:
                import openai

                return openai.AsyncOpenAI(
                    api_key=os.environ.get("OPENAI_API_KEY"),
                )
            except ImportError:
                raise ImportError("openai package not installed")

        elif provider == "cerebras":
            try:
                from cerebras.cloud.sdk import AsyncCerebras

                return AsyncCerebras(
                    api_key=os.environ.get("CEREBRAS_API_KEY"),
                )
            except ImportError:
                raise ImportError("cerebras-cloud-sdk package not installed")

        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def _close_connection(self, conn: PooledConnection) -> None:
        """Close a connection."""
        try:
            if hasattr(conn.client, "close"):
                await conn.client.close()
            elif hasattr(conn.client, "aclose"):
                await conn.client.aclose()
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

        self._stats[conn.provider]["closed"] += 1

    @asynccontextmanager
    async def acquire(
        self, provider: str, timeout: float | None = None
    ) -> AsyncGenerator[Any, None]:
        """Acquire a connection from the pool.

        Args:
            provider: The LLM provider name
            timeout: Optional timeout override

        Yields:
            The client instance

        Raises:
            TimeoutError: If no connection available within timeout
        """
        timeout = timeout or self.config.acquire_timeout
        semaphore = self._get_semaphore(provider)
        self._init_stats(provider)

        try:
            # Wait for available slot
            acquired = await asyncio.wait_for(
                semaphore.acquire(), timeout=timeout
            )
            if not acquired:
                self._stats[provider]["timeouts"] += 1
                raise TimeoutError(f"Timeout acquiring connection for {provider}")

        except asyncio.TimeoutError:
            self._stats[provider]["timeouts"] += 1
            raise TimeoutError(f"Timeout acquiring connection for {provider}")

        conn = None
        try:
            # Get or create connection
            async with self._get_lock(provider):
                pool = self._pools.setdefault(provider, [])

                # Find available connection
                for c in pool:
                    if not c.in_use and c.idle_time < self.config.idle_timeout:
                        conn = c
                        conn.in_use = True
                        break

                # Create new if needed
                if conn is None:
                    conn = await self._create_connection(provider)
                    conn.in_use = True
                    pool.append(conn)

            self._stats[provider]["acquired"] += 1
            conn.mark_used()

            yield conn.client

        except Exception as e:
            if conn:
                conn.mark_error()
            self._stats[provider]["errors"] += 1
            raise

        finally:
            if conn:
                conn.in_use = False
            self._stats[provider]["released"] += 1
            semaphore.release()

    async def execute(
        self,
        provider: str,
        method: str,
        *args,
        **kwargs,
    ) -> Any:
        """Execute a method on a pooled connection.

        Convenience method that handles acquire/release automatically.

        Args:
            provider: The LLM provider name
            method: Method name to call on the client
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            The method result
        """
        async with self.acquire(provider) as client:
            func = getattr(client, method)
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

    async def _health_check_loop(self) -> None:
        """Background task to check connection health."""
        while self._running:
            try:
                await asyncio.sleep(self.config.health_check_interval)
                await self._perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")

    async def _perform_health_checks(self) -> None:
        """Check health of all connections and remove stale ones."""
        for provider, pool in list(self._pools.items()):
            async with self._get_lock(provider):
                # Remove idle connections
                to_remove = []
                for conn in pool:
                    if not conn.in_use:
                        if conn.idle_time > self.config.idle_timeout:
                            to_remove.append(conn)
                        elif conn.error_count > 5:
                            to_remove.append(conn)

                for conn in to_remove:
                    pool.remove(conn)
                    await self._close_connection(conn)
                    logger.debug(f"Removed stale connection for {provider}")

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Get pool statistics."""
        stats = {}
        for provider, pool in self._pools.items():
            in_use = sum(1 for c in pool if c.in_use)
            stats[provider] = {
                "total": len(pool),
                "in_use": in_use,
                "available": len(pool) - in_use,
                **self._stats.get(provider, {}),
            }
        return stats

    def status(self) -> PoolStatus:
        """Get overall pool health status."""
        if not self._running:
            return PoolStatus.UNHEALTHY

        total_errors = sum(s.get("errors", 0) for s in self._stats.values())
        total_acquired = sum(s.get("acquired", 0) for s in self._stats.values())

        if total_acquired == 0:
            return PoolStatus.HEALTHY

        error_rate = total_errors / total_acquired
        if error_rate > 0.5:
            return PoolStatus.UNHEALTHY
        elif error_rate > 0.1:
            return PoolStatus.DEGRADED
        return PoolStatus.HEALTHY


# Global pool instance
_global_pool: ConnectionPool | None = None
_pool_lock = asyncio.Lock()


async def get_pool(config: PoolConfig | None = None) -> ConnectionPool:
    """Get or create the global connection pool.

    Thread-safe singleton pattern for the connection pool.

    Args:
        config: Optional configuration (only used on first call)

    Returns:
        The global ConnectionPool instance
    """
    global _global_pool

    if _global_pool is None:
        async with _pool_lock:
            if _global_pool is None:
                _global_pool = ConnectionPool(config)
                await _global_pool.start()

    return _global_pool


async def close_pool() -> None:
    """Close the global connection pool."""
    global _global_pool

    if _global_pool is not None:
        await _global_pool.stop()
        _global_pool = None


__all__ = [
    "ConnectionPool",
    "PoolConfig",
    "PooledConnection",
    "PoolStatus",
    "get_pool",
    "close_pool",
]
