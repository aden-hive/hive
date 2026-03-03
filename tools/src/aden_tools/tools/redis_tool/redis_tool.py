"""
Redis Tool - In-memory data store for key-value, hash, list, and pub/sub operations.

Supports:
- Redis connection URL (REDIS_URL) or individual host/port/password
- Key-value, hash, list, and set data structures
- Pub/sub messaging
- TTL management

Reference: https://redis.io/docs/latest/commands/
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_url(credentials: CredentialStoreAdapter | None) -> str | None:
    if credentials is not None:
        return credentials.get("redis")
    return os.getenv("REDIS_URL")


def _get_client(url: str):  # noqa: ANN202
    """Create a Redis client from URL. Imports redis lazily."""
    import redis

    return redis.from_url(url, decode_responses=True, socket_timeout=10)


def _auth_error() -> dict[str, Any]:
    return {
        "error": "REDIS_URL not set",
        "help": "Set REDIS_URL (e.g. redis://localhost:6379 or redis://:password@host:6379/0)",
    }


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Redis tools with the MCP server."""

    # ── Key-Value ───────────────────────────────────────────────

    @mcp.tool()
    def redis_get(key: str) -> dict[str, Any]:
        """
        Get the value of a Redis key.

        Args:
            key: The Redis key to retrieve

        Returns:
            Dict with key and value (null if key doesn't exist)
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key:
            return {"error": "key is required"}
        try:
            r = _get_client(url)
            value = r.get(key)
            return {"key": key, "value": value}
        except Exception as e:
            return {"error": f"Redis GET failed: {e!s}"}

    @mcp.tool()
    def redis_set(
        key: str,
        value: str,
        ttl: int = 0,
    ) -> dict[str, Any]:
        """
        Set a Redis key-value pair with optional TTL.

        Args:
            key: The Redis key
            value: The value to store
            ttl: Time-to-live in seconds (0 = no expiry)

        Returns:
            Dict with status confirmation
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key:
            return {"error": "key is required"}
        try:
            r = _get_client(url)
            if ttl > 0:
                r.setex(key, ttl, value)
            else:
                r.set(key, value)
            return {"status": "ok", "key": key}
        except Exception as e:
            return {"error": f"Redis SET failed: {e!s}"}

    @mcp.tool()
    def redis_delete(keys: str) -> dict[str, Any]:
        """
        Delete one or more Redis keys.

        Args:
            keys: Comma-separated key names to delete

        Returns:
            Dict with number of keys deleted
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not keys:
            return {"error": "keys is required"}
        try:
            r = _get_client(url)
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
            deleted = r.delete(*key_list)
            return {"deleted": deleted}
        except Exception as e:
            return {"error": f"Redis DELETE failed: {e!s}"}

    @mcp.tool()
    def redis_keys(pattern: str = "*", count: int = 100) -> dict[str, Any]:
        """
        List Redis keys matching a pattern using SCAN (non-blocking).

        Args:
            pattern: Glob-style pattern (default "*" for all keys)
            count: Maximum keys to return (default 100)

        Returns:
            Dict with matching keys list
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        count = max(1, min(count, 1000))
        try:
            r = _get_client(url)
            keys = []
            cursor = 0
            while len(keys) < count:
                cursor, batch = r.scan(cursor=cursor, match=pattern, count=min(count, 100))
                keys.extend(batch)
                if cursor == 0:
                    break
            return {"pattern": pattern, "keys": keys[:count]}
        except Exception as e:
            return {"error": f"Redis KEYS failed: {e!s}"}

    # ── Hash ────────────────────────────────────────────────────

    @mcp.tool()
    def redis_hset(
        key: str,
        field: str,
        value: str,
    ) -> dict[str, Any]:
        """
        Set a field in a Redis hash.

        Args:
            key: The hash key
            field: The field name within the hash
            value: The value to set

        Returns:
            Dict with status and whether the field was newly created
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key or not field:
            return {"error": "key and field are required"}
        try:
            r = _get_client(url)
            created = r.hset(key, field, value)
            return {"status": "ok", "key": key, "field": field, "created": bool(created)}
        except Exception as e:
            return {"error": f"Redis HSET failed: {e!s}"}

    @mcp.tool()
    def redis_hgetall(key: str) -> dict[str, Any]:
        """
        Get all fields and values from a Redis hash.

        Args:
            key: The hash key

        Returns:
            Dict with key and data (field-value mapping)
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key:
            return {"error": "key is required"}
        try:
            r = _get_client(url)
            data = r.hgetall(key)
            return {"key": key, "data": data}
        except Exception as e:
            return {"error": f"Redis HGETALL failed: {e!s}"}

    # ── List ────────────────────────────────────────────────────

    @mcp.tool()
    def redis_lpush(key: str, values: str) -> dict[str, Any]:
        """
        Push one or more values to the head of a Redis list.

        Args:
            key: The list key
            values: Comma-separated values to push

        Returns:
            Dict with new list length
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key or not values:
            return {"error": "key and values are required"}
        try:
            r = _get_client(url)
            val_list = [v.strip() for v in values.split(",") if v.strip()]
            length = r.lpush(key, *val_list)
            return {"key": key, "length": length}
        except Exception as e:
            return {"error": f"Redis LPUSH failed: {e!s}"}

    @mcp.tool()
    def redis_lrange(key: str, start: int = 0, stop: int = -1) -> dict[str, Any]:
        """
        Get a range of elements from a Redis list.

        Args:
            key: The list key
            start: Start index (0-based, default 0)
            stop: Stop index inclusive (-1 for all, default -1)

        Returns:
            Dict with key and items list
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key:
            return {"error": "key is required"}
        try:
            r = _get_client(url)
            items = r.lrange(key, start, stop)
            return {"key": key, "items": items}
        except Exception as e:
            return {"error": f"Redis LRANGE failed: {e!s}"}

    # ── Pub/Sub ─────────────────────────────────────────────────

    @mcp.tool()
    def redis_publish(channel: str, message: str) -> dict[str, Any]:
        """
        Publish a message to a Redis channel.

        Args:
            channel: Channel name to publish to
            message: Message content to publish

        Returns:
            Dict with channel and number of subscribers that received the message
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not channel or not message:
            return {"error": "channel and message are required"}
        try:
            r = _get_client(url)
            receivers = r.publish(channel, message)
            return {"channel": channel, "receivers": receivers}
        except Exception as e:
            return {"error": f"Redis PUBLISH failed: {e!s}"}

    # ── Utility ─────────────────────────────────────────────────

    @mcp.tool()
    def redis_info() -> dict[str, Any]:
        """
        Get Redis server information and statistics.

        Returns:
            Dict with server version, connected_clients, used_memory_human,
            total_connections_received, and keyspace info
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        try:
            r = _get_client(url)
            info = r.info()
            return {
                "redis_version": info.get("redis_version", ""),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", ""),
                "total_connections_received": info.get("total_connections_received", 0),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0),
                "db0": info.get("db0", {}),
            }
        except Exception as e:
            return {"error": f"Redis INFO failed: {e!s}"}

    @mcp.tool()
    def redis_ttl(key: str) -> dict[str, Any]:
        """
        Get the time-to-live of a Redis key in seconds.

        Args:
            key: The Redis key to check

        Returns:
            Dict with key and ttl (-1 = no expiry, -2 = key doesn't exist)
        """
        url = _get_url(credentials)
        if not url:
            return _auth_error()
        if not key:
            return {"error": "key is required"}
        try:
            r = _get_client(url)
            ttl_val = r.ttl(key)
            return {"key": key, "ttl": ttl_val}
        except Exception as e:
            return {"error": f"Redis TTL failed: {e!s}"}
