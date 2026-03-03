"""
Redis MCP Tool

Provides access to Redis for agent state persistence and heavy payload orchestration.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import redis.asyncio as redis
from fastmcp import FastMCP

from aden_tools.credentials import CREDENTIAL_SPECS
from aden_tools.credentials.store_adapter import CredentialStoreAdapter

logger = logging.getLogger(__name__)

# Global client for reuse
_redis_client: Optional[redis.Redis] = None
_last_url: Optional[str] = None


async def _get_client(redis_url: str) -> redis.Redis:
    """Securely initializes or retrieves the Redis client."""
    global _redis_client, _last_url
    if _redis_client is not None and _last_url == redis_url:
        return _redis_client

    if _redis_client is not None:
        await _redis_client.aclose()

    _redis_client = redis.from_url(redis_url, decode_responses=True)
    _last_url = redis_url
    return _redis_client


def _error_response(message: str) -> dict:
    return {"error": message, "success": False}


def _missing_credential_response() -> dict:
    spec = CREDENTIAL_SPECS["redis"]
    return {
        "error": f"Missing required credential: {spec.description}",
        "help": spec.api_key_instructions,
        "success": False,
    }


def _get_redis_url(
    credentials: CredentialStoreAdapter | None,
) -> str | None:
    redis_url: str | None = None

    if credentials:
        redis_url = credentials.get("redis")

    if not redis_url:
        redis_url = os.getenv("REDIS_URL")

    return redis_url


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Redis tools with the MCP server."""

    @mcp.tool()
    async def redis_set(key: str, value: str, ttl_seconds: int = 300) -> dict:
        """
        Stores a payload in Redis with a TTL.

        Args:
            key (str): The key to store the value under.
            value (str): The string value to store.
            ttl_seconds (int): Time-to-live in seconds. Default is 300.
        """
        redis_url = _get_redis_url(credentials)
        if not redis_url:
            return _missing_credential_response()

        try:
            client = await _get_client(redis_url)
            await client.setex(name=key, time=ttl_seconds, value=value)
            return {
                "message": f"SUCCESS: Payload stored at key '{key}' with TTL {ttl_seconds}s.",
                "success": True,
            }
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return _error_response(f"Redis error: {str(e)}")

    @mcp.tool()
    async def redis_get(key: str) -> dict:
        """
        Retrieves a payload by key.

        Args:
            key (str): The key to retrieve.
        """
        redis_url = _get_redis_url(credentials)
        if not redis_url:
            return _missing_credential_response()

        try:
            client = await _get_client(redis_url)
            data = await client.get(key)
            if data is None:
                return _error_response(f"Key '{key}' not found or has expired.")
            return {"value": data, "success": True}
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return _error_response(f"Redis error: {str(e)}")

    @mcp.tool()
    async def redis_ping() -> dict:
        """Diagnostic health check for the Redis connection."""
        redis_url = _get_redis_url(credentials)
        if not redis_url:
            return _missing_credential_response()

        try:
            client = await _get_client(redis_url)
            response = await client.ping()
            return {"message": "PONG" if response else "ERROR: Unreachable", "success": bool(response)}
        except Exception as e:
            logger.error(f"Redis ping error: {e}")
            return _error_response(f"Redis error: {str(e)}")
