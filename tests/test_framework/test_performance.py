"""Performance tests."""

import pytest
from core.framework.testing.performance import (
    TestAgentPerformance,
    TestConfigPerformance
)


@pytest.mark.benchmark(group="agent")
class TestAgentBenchmarks(TestAgentPerformance):
    """Agent performance benchmarks."""
    pass


@pytest.mark.benchmark(group="config")
class TestConfigBenchmarks(TestConfigPerformance):
    """Config performance benchmarks."""
    pass


def test_profiling_example():
    """Example of using profiling utility."""
    from core.framework.testing.performance import profile_execution

    def sample_function():
        total = 0
        for i in range(1000):
            total += i
        return total

    result, stats = profile_execution(sample_function)
    assert result == 499500
    assert "function calls" in stats
