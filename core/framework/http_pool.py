"""
HTTP Connection Pooling

Shared connection pools for efficient HTTP requests with:
- HTTP/2 multiplexing support
- Automatic connection reuse
- Configurable limits and timeouts
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class PooledHTTPClient:
    """
    Singleton HTTP client with connection pooling.
    
    Features:
    - HTTP/2 multiplexing for reduced latency
    - Connection reuse across requests
    - Configurable limits and timeouts
    - Automatic retry on transient failures
    
    Usage:
        # Get shared client for a base URL
        client = await PooledHTTPClient.get_client("https://api.openai.com")
        response = await client.post("/v1/chat/completions", json=data)
        
        # Or use the singleton directly
        pool = PooledHTTPClient.get_instance()
        client = await pool.get_client("https://api.anthropic.com")
    """
    
    _instance: Optional["PooledHTTPClient"] = None
    _lock: asyncio.Lock = asyncio.Lock()
    
    def __init__(
        self,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        keepalive_expiry: float = 30.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 60.0,
        write_timeout: float = 30.0,
    ):
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.keepalive_expiry = keepalive_expiry
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        
        # Client cache per base URL
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._client_lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> "PooledHTTPClient":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    async def get_client(cls, base_url: str = "") -> httpx.AsyncClient:
        """Get a pooled client for the given base URL."""
        instance = cls.get_instance()
        return await instance._get_or_create_client(base_url)
    
    async def _get_or_create_client(self, base_url: str) -> httpx.AsyncClient:
        """Get or create a client for the base URL."""
        async with self._client_lock:
            if base_url not in self._clients:
                limits = httpx.Limits(
                    max_connections=self.max_connections,
                    max_keepalive_connections=self.max_keepalive_connections,
                    keepalive_expiry=self.keepalive_expiry,
                )
                
                timeout = httpx.Timeout(
                    connect=self.connect_timeout,
                    read=self.read_timeout,
                    write=self.write_timeout,
                    pool=self.connect_timeout,
                )
                
                self._clients[base_url] = httpx.AsyncClient(
                    base_url=base_url if base_url else None,
                    limits=limits,
                    timeout=timeout,
                    http2=True,  # Enable HTTP/2
                    follow_redirects=True,
                )
                
                logger.debug(f"Created pooled HTTP client for: {base_url or 'default'}")
            
            return self._clients[base_url]
    
    async def close(self, base_url: Optional[str] = None) -> None:
        """
        Close client(s).
        
        Args:
            base_url: Specific client to close, or None for all
        """
        async with self._client_lock:
            if base_url:
                if base_url in self._clients:
                    await self._clients[base_url].aclose()
                    del self._clients[base_url]
            else:
                for client in self._clients.values():
                    await client.aclose()
                self._clients.clear()
    
    @classmethod
    async def close_all(cls) -> None:
        """Close all pooled clients."""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
    
    def get_stats(self) -> dict[str, Any]:
        """Get connection pool statistics."""
        stats = {}
        for base_url, client in self._clients.items():
            pool = client._transport._pool if hasattr(client._transport, "_pool") else None
            stats[base_url or "default"] = {
                "active": True,
                "http2": True,
            }
        return stats


class RetryingHTTPClient:
    """
    HTTP client wrapper with automatic retry.
    
    Retries on:
    - Connection errors
    - Timeouts
    - 5xx server errors
    - 429 rate limit errors (with backoff)
    """
    
    def __init__(
        self,
        client: httpx.AsyncClient,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_multiplier: float = 2.0,
        retry_on_status: tuple[int, ...] = (429, 500, 502, 503, 504),
    ):
        self.client = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_multiplier = retry_multiplier
        self.retry_on_status = retry_on_status
    
    async def request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Make a request with retry logic."""
        last_exception: Optional[Exception] = None
        delay = self.retry_delay
        
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.request(method, url, **kwargs)
                
                # Check if we should retry on this status
                if response.status_code in self.retry_on_status:
                    if attempt < self.max_retries:
                        # Get retry-after header if present
                        retry_after = response.headers.get("retry-after")
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                pass
                        
                        logger.warning(
                            f"Retrying request to {url} after status {response.status_code} "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(delay)
                        delay *= self.retry_multiplier
                        continue
                
                return response
                
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"Retrying request to {url} after {type(e).__name__} "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    delay *= self.retry_multiplier
                    continue
                raise
        
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry loop exit")
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET request with retry."""
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST request with retry."""
        return await self.request("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT request with retry."""
        return await self.request("PUT", url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE request with retry."""
        return await self.request("DELETE", url, **kwargs)


async def get_http_client(
    base_url: str = "",
    with_retry: bool = True,
    **retry_kwargs,
) -> httpx.AsyncClient | RetryingHTTPClient:
    """
    Get a configured HTTP client.
    
    Args:
        base_url: Base URL for the client
        with_retry: Wrap with retry logic
        **retry_kwargs: Options for RetryingHTTPClient
    
    Returns:
        Configured HTTP client
    """
    client = await PooledHTTPClient.get_client(base_url)
    
    if with_retry:
        return RetryingHTTPClient(client, **retry_kwargs)
    
    return client
