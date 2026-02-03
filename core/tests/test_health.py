"""
tests for the health check module.

tests component health checks, status aggregation, and helpers.
"""

import tempfile
from unittest.mock import MagicMock

import pytest

from framework.health import (
    ComponentHealth,
    HealthChecker,
    HealthReport,
    HealthStatus,
    check_runtime_responsive,
    check_storage_accessible,
)


class TestComponentHealth:
    """test the component health dataclass"""

    def test_create_healthy_component(self):
        health = ComponentHealth(
            name="database",
            healthy=True,
            message="connected",
        )

        assert health.name == "database"
        assert health.healthy is True
        assert health.message == "connected"
        assert health.error is None

    def test_create_unhealthy_component(self):
        health = ComponentHealth(
            name="cache",
            healthy=False,
            error="connection refused",
        )

        assert health.healthy is False
        assert health.error == "connection refused"


class TestHealthReport:
    """test health report generation"""

    def test_to_dict(self):
        report = HealthReport(
            status=HealthStatus.HEALTHY,
            components={
                "db": ComponentHealth(name="db", healthy=True),
            },
        )

        d = report.to_dict()

        assert d["status"] == "healthy"
        assert d["healthy"] is True
        assert "timestamp" in d
        assert "db" in d["components"]
        assert d["components"]["db"]["healthy"] is True


class TestHealthChecker:
    """test the health checker"""

    @pytest.mark.asyncio
    async def test_empty_checker_is_healthy(self):
        checker = HealthChecker()
        report = await checker.run_checks()

        assert report.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_sync_check_passing(self):
        checker = HealthChecker()
        checker.add_check("test", lambda: True)

        report = await checker.run_checks()

        assert report.status == HealthStatus.HEALTHY
        assert "test" in report.components
        assert report.components["test"].healthy is True

    @pytest.mark.asyncio
    async def test_sync_check_failing(self):
        checker = HealthChecker()
        checker.add_check("test", lambda: False)

        report = await checker.run_checks()

        assert report.status == HealthStatus.UNHEALTHY
        assert report.components["test"].healthy is False

    @pytest.mark.asyncio
    async def test_sync_check_returns_dict(self):
        checker = HealthChecker()
        checker.add_check(
            "test",
            lambda: {
                "healthy": True,
                "message": "all good",
                "details": {"version": "1.0"},
            },
        )

        report = await checker.run_checks()

        assert report.components["test"].healthy is True
        assert report.components["test"].message == "all good"
        assert report.components["test"].details["version"] == "1.0"

    @pytest.mark.asyncio
    async def test_sync_check_raises_exception(self):
        checker = HealthChecker()
        checker.add_check("test", lambda: 1 / 0)  # will raise ZeroDivisionError

        report = await checker.run_checks()

        assert report.status == HealthStatus.UNHEALTHY
        assert report.components["test"].healthy is False
        assert "ZeroDivisionError" in report.components["test"].message

    @pytest.mark.asyncio
    async def test_async_check_passing(self):
        checker = HealthChecker()

        async def async_check():
            return True

        checker.add_check("test", async_check, is_async=True)

        report = await checker.run_checks()

        assert report.status == HealthStatus.HEALTHY
        assert report.components["test"].healthy is True

    @pytest.mark.asyncio
    async def test_async_check_failing(self):
        checker = HealthChecker()

        async def async_check():
            return {"healthy": False, "error": "connection timeout"}

        checker.add_check("test", async_check, is_async=True)

        report = await checker.run_checks()

        assert report.status == HealthStatus.UNHEALTHY
        assert report.components["test"].error == "connection timeout"

    @pytest.mark.asyncio
    async def test_mixed_checks_degraded(self):
        """if some checks pass and some fail, status is degraded"""
        checker = HealthChecker()
        checker.add_check("passing", lambda: True)
        checker.add_check("failing", lambda: False)

        report = await checker.run_checks()

        assert report.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_all_failing_is_unhealthy(self):
        checker = HealthChecker()
        checker.add_check("fail1", lambda: False)
        checker.add_check("fail2", lambda: False)

        report = await checker.run_checks()

        assert report.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_is_healthy_method(self):
        checker = HealthChecker()
        checker.add_check("test", lambda: True)

        assert await checker.is_healthy() is True

        checker.add_check("broken", lambda: False)
        assert await checker.is_healthy() is False

    @pytest.mark.asyncio
    async def test_remove_check(self):
        checker = HealthChecker()
        checker.add_check("test", lambda: False)

        # should be unhealthy
        assert await checker.is_healthy() is False

        # remove the failing check
        removed = checker.remove_check("test")
        assert removed is True

        # now should be healthy (no checks = healthy)
        assert await checker.is_healthy() is True

    @pytest.mark.asyncio
    async def test_check_unknown_component(self):
        checker = HealthChecker()

        health = await checker.check_component("nonexistent")

        assert health.healthy is False
        assert "no check registered" in health.error


class TestStorageHealthCheck:
    """test the storage health check helper"""

    def test_storage_accessible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = check_storage_accessible(tmpdir)

            assert result["healthy"] is True
            assert result["message"] == "storage accessible"

    def test_storage_not_exists(self):
        result = check_storage_accessible("/nonexistent/path/12345")

        assert result["healthy"] is False
        assert "does not exist" in result["message"]


class TestRuntimeHealthCheck:
    """test the runtime health check helper"""

    @pytest.mark.asyncio
    async def test_runtime_not_running(self):
        mock_runtime = MagicMock()
        mock_runtime.is_running = False

        result = await check_runtime_responsive(mock_runtime)

        assert result["healthy"] is False
        assert "not running" in result["message"]

    @pytest.mark.asyncio
    async def test_runtime_running(self):
        mock_runtime = MagicMock()
        mock_runtime.is_running = True
        mock_runtime.get_stats.return_value = {
            "running": True,
            "entry_points": 2,
        }

        result = await check_runtime_responsive(mock_runtime)

        assert result["healthy"] is True
        assert result["details"]["entry_points"] == 2

    @pytest.mark.asyncio
    async def test_runtime_raises_exception(self):
        mock_runtime = MagicMock()
        mock_runtime.is_running = True
        mock_runtime.get_stats.side_effect = Exception("internal error")

        result = await check_runtime_responsive(mock_runtime)

        assert result["healthy"] is False
        assert "internal error" in result["error"]
