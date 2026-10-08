"""Tests for redis_tool - Redis in-memory data store integration."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.redis_tool.redis_tool import register_tools

ENV = {"REDIS_URL": "redis://localhost:6379"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def mock_redis():
    """Mock redis.from_url to return a mock client."""
    mock_client = MagicMock()
    mock_mod = MagicMock()
    mock_mod.from_url.return_value = mock_client
    with patch.dict("sys.modules", {"redis": mock_mod}):
        yield mock_client


class TestRedisGet:
    def test_missing_url(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["redis_get"](key="mykey")
        assert "error" in result

    def test_missing_key(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_get"](key="")
        assert "error" in result

    def test_successful_get(self, tool_fns, mock_redis):
        mock_redis.get.return_value = "hello"
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_get"](key="mykey")
        assert result["key"] == "mykey"
        assert result["value"] == "hello"

    def test_key_not_found(self, tool_fns, mock_redis):
        mock_redis.get.return_value = None
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_get"](key="missing")
        assert result["value"] is None


class TestRedisSet:
    def test_successful_set(self, tool_fns, mock_redis):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_set"](key="k", value="v")
        assert result["status"] == "ok"
        mock_redis.set.assert_called_once_with("k", "v")

    def test_set_with_ttl(self, tool_fns, mock_redis):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_set"](key="k", value="v", ttl=60)
        assert result["status"] == "ok"
        mock_redis.setex.assert_called_once_with("k", 60, "v")


class TestRedisDelete:
    def test_missing_keys(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_delete"](keys="")
        assert "error" in result

    def test_successful_delete(self, tool_fns, mock_redis):
        mock_redis.delete.return_value = 2
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_delete"](keys="a, b")
        assert result["deleted"] == 2


class TestRedisKeys:
    def test_successful_scan(self, tool_fns, mock_redis):
        mock_redis.scan.return_value = (0, ["key1", "key2"])
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_keys"](pattern="key*")
        assert result["pattern"] == "key*"
        assert result["keys"] == ["key1", "key2"]


class TestRedisHash:
    def test_hset(self, tool_fns, mock_redis):
        mock_redis.hset.return_value = 1
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_hset"](key="h", field="f", value="v")
        assert result["status"] == "ok"
        assert result["created"] is True

    def test_hgetall(self, tool_fns, mock_redis):
        mock_redis.hgetall.return_value = {"name": "Alice", "age": "30"}
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_hgetall"](key="user:1")
        assert result["data"]["name"] == "Alice"


class TestRedisList:
    def test_lpush(self, tool_fns, mock_redis):
        mock_redis.lpush.return_value = 3
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_lpush"](key="q", values="a, b, c")
        assert result["length"] == 3

    def test_lrange(self, tool_fns, mock_redis):
        mock_redis.lrange.return_value = ["c", "b", "a"]
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_lrange"](key="q")
        assert result["items"] == ["c", "b", "a"]


class TestRedisPublish:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_publish"](channel="", message="")
        assert "error" in result

    def test_successful_publish(self, tool_fns, mock_redis):
        mock_redis.publish.return_value = 2
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_publish"](channel="events", message="hello")
        assert result["receivers"] == 2


class TestRedisInfo:
    def test_successful_info(self, tool_fns, mock_redis):
        mock_redis.info.return_value = {
            "redis_version": "7.2.0",
            "connected_clients": 5,
            "used_memory_human": "1.5M",
            "total_connections_received": 100,
            "uptime_in_seconds": 86400,
            "db0": {"keys": 42},
        }
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_info"]()
        assert result["redis_version"] == "7.2.0"
        assert result["connected_clients"] == 5


class TestRedisTtl:
    def test_missing_key(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_ttl"](key="")
        assert "error" in result

    def test_successful_ttl(self, tool_fns, mock_redis):
        mock_redis.ttl.return_value = 300
        with patch.dict("os.environ", ENV):
            result = tool_fns["redis_ttl"](key="session:1")
        assert result["ttl"] == 300
