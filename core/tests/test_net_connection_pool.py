"""Tests for framework.net.connection_pool module."""

import pytest

from framework.net.connection_pool import ConnectionPool, PoolConfig, PoolStats


class TestPoolStats:
    def test_avg_latency_zero_requests(self):
        stats = PoolStats()
        assert stats.avg_latency_ms == 0.0

    def test_avg_latency(self):
        stats = PoolStats(successful_requests=10, total_latency_ms=500.0)
        assert stats.avg_latency_ms == 50.0

    def test_error_rate(self):
        stats = PoolStats(total_requests=100, failed_requests=5)
        assert stats.error_rate == 0.05

    def test_to_dict(self):
        stats = PoolStats(total_requests=1, successful_requests=1)
        d = stats.to_dict()
        assert "total_requests" in d
        assert "error_rate" in d


class TestPoolConfig:
    def test_defaults(self):
        config = PoolConfig()
        assert config.max_connections == 100
        assert config.retries == 3
        assert config.user_agent == "hive-agent/1.0"


class TestConnectionPool:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with ConnectionPool() as pool:
            assert pool is not None
            assert pool.stats.total_requests == 0

    @pytest.mark.asyncio
    async def test_close_without_open(self):
        pool = ConnectionPool()
        await pool.close()  # Should not raise
