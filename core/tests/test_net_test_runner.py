"""Tests for framework.net.test_runner module."""

import pytest

from framework.net.test_runner import (
    ContinuousTestRunner,
    TestConfig,
    TestResult,
    TestSuite,
    run_test_suite,
)


class TestRunTestSuite:
    @pytest.mark.asyncio
    async def test_passing_command(self):
        config = TestConfig(
            name="echo-test",
            suite=TestSuite.SMOKE,
            command="echo hello",
            timeout=10.0,
        )
        result = await run_test_suite(config)
        assert result.passed
        assert result.exit_code == 0
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_failing_command(self):
        config = TestConfig(
            name="fail-test",
            suite=TestSuite.SMOKE,
            command="exit 1",
            timeout=10.0,
        )
        result = await run_test_suite(config)
        assert not result.passed
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_timeout(self):
        config = TestConfig(
            name="timeout-test",
            suite=TestSuite.SMOKE,
            command="sleep 10",
            timeout=0.2,
        )
        result = await run_test_suite(config)
        assert not result.passed
        assert result.exit_code == -1
        assert "timed out" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_to_check_result(self):
        config = TestConfig(name="cr-test", suite=TestSuite.UNIT, command="echo ok")
        result = await run_test_suite(config)
        cr = result.to_check_result()
        assert cr.name == "test:cr-test"
        assert cr.is_healthy


class TestContinuousTestRunner:
    @pytest.mark.asyncio
    async def test_run_all(self):
        suites = [
            TestConfig(name="pass", suite=TestSuite.SMOKE, command="echo ok"),
            TestConfig(name="fail", suite=TestSuite.SMOKE, command="exit 1"),
        ]
        runner = ContinuousTestRunner(suites)
        results = await runner.run_all()
        assert len(results) == 2
        assert results[0].passed
        assert not results[1].passed

    @pytest.mark.asyncio
    async def test_merge_ready_all_pass(self):
        suites = [
            TestConfig(name="a", suite=TestSuite.UNIT, command="echo ok", required_for_merge=True),
        ]
        runner = ContinuousTestRunner(suites)
        await runner.run_all()
        assert runner.merge_ready

    @pytest.mark.asyncio
    async def test_merge_blocked(self):
        suites = [
            TestConfig(name="a", suite=TestSuite.UNIT, command="exit 1", required_for_merge=True),
        ]
        runner = ContinuousTestRunner(suites)
        await runner.run_all()
        assert not runner.merge_ready

    @pytest.mark.asyncio
    async def test_gate_summary(self):
        suites = [
            TestConfig(name="a", suite=TestSuite.UNIT, command="echo ok", required_for_merge=True),
            TestConfig(
                name="b", suite=TestSuite.SMOKE, command="echo ok", required_for_merge=False
            ),
        ]
        runner = ContinuousTestRunner(suites)
        await runner.run_all()
        summary = runner.gate_summary
        assert summary["merge_ready"] is True
        assert summary["passing"] == 2
        assert summary["total"] == 2

    @pytest.mark.asyncio
    async def test_on_result_callback(self):
        collected: list[TestResult] = []
        suites = [TestConfig(name="cb", suite=TestSuite.UNIT, command="echo hi")]
        runner = ContinuousTestRunner(suites, on_result=lambda r: collected.append(r))
        await runner.run_all()
        assert len(collected) == 1
        assert collected[0].passed
