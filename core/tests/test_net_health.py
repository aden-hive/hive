"""Tests for framework.net.health module."""

import asyncio
import time

import pytest

from framework.net.health import (
    BaseHealthCheck,
    CheckResult,
    CompositeHealthCheck,
    HealthChecker,
    HealthStatus,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class AlwaysHealthyCheck(BaseHealthCheck):
    async def check(self) -> CheckResult:
        return CheckResult(name=self.name, status=HealthStatus.HEALTHY, message="All good")


class AlwaysUnhealthyCheck(BaseHealthCheck):
    async def check(self) -> CheckResult:
        return CheckResult(name=self.name, status=HealthStatus.UNHEALTHY, message="Broken")


class SlowCheck(BaseHealthCheck):
    async def check(self) -> CheckResult:
        await asyncio.sleep(10)
        return CheckResult(name=self.name, status=HealthStatus.HEALTHY)


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------


class TestCheckResult:
    def test_is_healthy(self):
        r = CheckResult(name="t", status=HealthStatus.HEALTHY)
        assert r.is_healthy is True

    def test_is_not_healthy(self):
        r = CheckResult(name="t", status=HealthStatus.UNHEALTHY)
        assert r.is_healthy is False

    def test_to_dict_keys(self):
        r = CheckResult(name="t", status=HealthStatus.HEALTHY, message="ok", latency_ms=42.5)
        d = r.to_dict()
        assert d["name"] == "t"
        assert d["status"] == "success"
        assert d["latency_ms"] == 42.5

    def test_timestamp_auto_set(self):
        before = time.time()
        r = CheckResult(name="t", status=HealthStatus.HEALTHY)
        after = time.time()
        assert before <= r.timestamp <= after


# ---------------------------------------------------------------------------
# CompositeHealthCheck
# ---------------------------------------------------------------------------


class TestCompositeHealthCheck:
    @pytest.mark.asyncio
    async def test_all_healthy(self):
        comp = CompositeHealthCheck(
            "c", [AlwaysHealthyCheck("a"), AlwaysHealthyCheck("b")], mode="all"
        )
        result = await comp.timed_check()
        assert result.is_healthy
        assert "2/2" in result.message

    @pytest.mark.asyncio
    async def test_one_unhealthy_all_mode(self):
        comp = CompositeHealthCheck(
            "c", [AlwaysHealthyCheck("a"), AlwaysUnhealthyCheck("b")], mode="all"
        )
        result = await comp.timed_check()
        assert not result.is_healthy

    @pytest.mark.asyncio
    async def test_any_mode_one_healthy(self):
        comp = CompositeHealthCheck(
            "c", [AlwaysHealthyCheck("a"), AlwaysUnhealthyCheck("b")], mode="any"
        )
        result = await comp.timed_check()
        assert result.is_healthy

    @pytest.mark.asyncio
    async def test_majority_mode(self):
        comp = CompositeHealthCheck(
            "c",
            [AlwaysHealthyCheck("a"), AlwaysHealthyCheck("b"), AlwaysUnhealthyCheck("c")],
            mode="majority",
        )
        result = await comp.timed_check()
        assert result.is_healthy  # 2/3


# ---------------------------------------------------------------------------
# BaseHealthCheck
# ---------------------------------------------------------------------------


class TestBaseHealthCheck:
    @pytest.mark.asyncio
    async def test_timed_check_adds_latency(self):
        check = AlwaysHealthyCheck("l")
        result = await check.timed_check()
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        check = SlowCheck("slow", timeout=0.1)
        result = await check.timed_check()
        assert result.status == HealthStatus.UNHEALTHY
        assert "Timed out" in result.message


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------


class TestHealthChecker:
    @pytest.mark.asyncio
    async def test_run_once(self):
        checker = HealthChecker([AlwaysHealthyCheck("a"), AlwaysHealthyCheck("b")])
        results = await checker.run_once()
        assert len(results) == 2
        assert checker.overall_status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_overall_unhealthy(self):
        checker = HealthChecker([AlwaysHealthyCheck("a"), AlwaysUnhealthyCheck("b")])
        await checker.run_once()
        assert checker.overall_status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_state_change_callback(self):
        changes: list[tuple[HealthStatus, HealthStatus]] = []

        def on_change(prev: CheckResult, curr: CheckResult):
            changes.append((prev.status, curr.status))

        checker = HealthChecker([AlwaysHealthyCheck("a")], on_state_change=on_change)
        await checker.run_once()
        assert len(changes) == 1
        assert changes[0] == (HealthStatus.UNKNOWN, HealthStatus.HEALTHY)

    @pytest.mark.asyncio
    async def test_summary(self):
        checker = HealthChecker([AlwaysHealthyCheck("a")])
        await checker.run_once()
        s = checker.summary()
        assert s["overall"] == "success"
        assert s["healthy"] == 1
        assert s["total"] == 1

    @pytest.mark.asyncio
    async def test_history_limit(self):
        checker = HealthChecker([AlwaysHealthyCheck("a")], history_size=3)
        for _ in range(5):
            await checker.run_once()
        assert len(checker._history["a"]) == 3
