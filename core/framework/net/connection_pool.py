"""
Managed async HTTP connection pool for Hive agents.
Wraps httpx with circuit breakers, retries, and structured logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from framework.net.circuit_breaker import CircuitBreaker
from framework.net.retry import retry_with_backoff

logger = logging.getLogger("framework.net.pool")


@dataclass
class PoolStats:
    """Connection pool statistics."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    active_connections: int = 0

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "error_rate": round(self.error_rate, 4),
            "active_connections": self.active_connections,
        }


@dataclass
class PoolConfig:
    """Connection pool configuration."""

    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 30.0
    timeout: float = 30.0
    connect_timeout: float = 10.0
    retries: int = 3
    retry_backoff_base: float = 1.0
    retry_backoff_max: float = 30.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery: float = 60.0
    user_agent: str = "hive-agent/1.0"
    default_headers: dict[str, str] = field(default_factory=dict)


class ConnectionPool:
    """
    Production-grade async connection pool.

    Features:
    - Connection pooling via httpx
    - Per-host circuit breakers
    - Automatic retries with exponential backoff
    - Request/response timing and stats
    - Structured logging
    """

    def __init__(self, config: PoolConfig | None = None):
        self.config = config or PoolConfig()
        self._client: httpx.AsyncClient | None = None
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._stats = PoolStats()
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=self.config.max_connections,
                    max_keepalive_connections=self.config.max_keepalive_connections,
                    keepalive_expiry=self.config.keepalive_expiry,
                ),
                timeout=httpx.Timeout(
                    self.config.timeout,
                    connect=self.config.connect_timeout,
                ),
                headers={
                    "User-Agent": self.config.user_agent,
                    **self.config.default_headers,
                },
                follow_redirects=True,
            )
        return self._client

    def _get_circuit_breaker(self, host: str) -> CircuitBreaker:
        if host not in self._circuit_breakers:
            self._circuit_breakers[host] = CircuitBreaker(
                name=f"pool-{host}",
                failure_threshold=self.config.circuit_breaker_threshold,
                recovery_timeout=self.config.circuit_breaker_recovery,
            )
        return self._circuit_breakers[host]

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        data: Any = None,
        params: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with circuit breaker and retries."""
        parsed = httpx.URL(url)
        host = parsed.host or "unknown"
        breaker = self._get_circuit_breaker(host)
        max_retries = retries if retries is not None else self.config.retries

        async def _do_request() -> httpx.Response:
            async with breaker:
                client = await self._get_client()
                self._stats.total_requests += 1
                self._stats.active_connections += 1
                start = time.monotonic()

                try:
                    resp = await client.request(
                        method,
                        url,
                        headers=headers,
                        json=json,
                        content=data,
                        params=params,
                    )
                    latency = (time.monotonic() - start) * 1000
                    self._stats.successful_requests += 1
                    self._stats.total_latency_ms += latency

                    logger.debug(
                        "request",
                        extra={
                            "method": method,
                            "url": url,
                            "status": resp.status_code,
                            "latency_ms": round(latency, 2),
                        },
                    )

                    # Raise for 5xx to trigger retries
                    if resp.status_code >= 500:
                        resp.raise_for_status()

                    return resp
                except Exception:
                    self._stats.failed_requests += 1
                    raise
                finally:
                    self._stats.active_connections -= 1

        return await retry_with_backoff(
            _do_request,
            max_retries=max_retries,
            base_delay=self.config.retry_backoff_base,
            max_delay=self.config.retry_backoff_max,
            retryable_exceptions=(
                httpx.HTTPStatusError,
                httpx.ConnectError,
                httpx.TimeoutException,
            ),
        )

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    @property
    def stats(self) -> PoolStats:
        return self._stats

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> ConnectionPool:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
