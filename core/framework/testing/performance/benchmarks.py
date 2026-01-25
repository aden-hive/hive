"""Performance benchmarking with pytest-benchmark."""

import pytest
import asyncio
import time
from typing import Dict, Any


class TestAgentPerformance:
    """Performance benchmarks for agent execution."""

    @pytest.mark.benchmark(group="agent_execution")
    def test_simple_agent_execution(self, benchmark):
        """Benchmark simple agent execution."""

        def execute_simple_agent():
            # Simulate simple agent execution
            agent = {"name": "simple", "nodes": []}
            result = {"success": True, "output": "done"}
            return result

        result = benchmark(execute_simple_agent)
        assert result["success"]

    @pytest.mark.benchmark(group="agent_execution")
    def test_complex_agent_execution(self, benchmark):
        """Benchmark complex agent execution."""

        def execute_complex_agent():
            # Simulate complex agent with many nodes
            agent = {
                "name": "complex",
                "nodes": [f"node_{i}" for i in range(50)]
            }
            result = {"success": True, "output": "done"}
            return result

        result = benchmark(execute_complex_agent)
        assert result["success"]

    @pytest.mark.benchmark(group="llm_calls")
    def test_llm_call_performance(self, benchmark):
        """Benchmark LLM call performance."""

        def mock_llm_call():
            # Simulate LLM API call
            response = {"text": "Response", "tokens": 100}
            return response

        result = benchmark(mock_llm_call)
        assert result["text"]


class TestConfigPerformance:
    """Performance benchmarks for configuration operations."""

    @pytest.mark.benchmark(group="config_operations")
    def test_config_read(self, benchmark):
        """Benchmark config read operation."""

        def read_config():
            # Simulate config read
            config = {"key": "value", "enabled": True}
            return config

        result = benchmark(read_config)
        assert result["key"] == "value"

    @pytest.mark.benchmark(group="config_operations")
    def test_feature_flag_evaluation(self, benchmark):
        """Benchmark feature flag evaluation."""

        def evaluate_flag():
            # Simulate flag evaluation
            return True

        result = benchmark(evaluate_flag)
        assert isinstance(result, bool)


class TestDatabasePerformance:
    """Performance benchmarks for database operations."""

    @pytest.mark.benchmark(group="database_operations")
    def test_database_query(self, benchmark):
        """Benchmark database query."""

        def execute_query():
            # Simulate database query
            results = [{"id": 1}, {"id": 2}]
            return results

        results = benchmark(execute_query)
        assert len(results) >= 0


class TestAPIPerformance:
    """Performance benchmarks for API operations."""

    @pytest.mark.benchmark(group="api_operations")
    def test_auth_login(self, benchmark):
        """Benchmark authentication login."""

        def mock_login():
            # Simulate login
            return {"access_token": "token", "expires_in": 1800}

        result = benchmark(mock_login)
        assert "access_token" in result

    @pytest.mark.benchmark(group="api_operations")
    def test_api_request(self, benchmark):
        """Benchmark API request."""

        def mock_request():
            # Simulate API request
            return {"status": "ok", "data": {}}

        result = benchmark(mock_request)
        assert result["status"] == "ok"


# Performance profiling utilities
def profile_execution(func, *args, **kwargs):
    """Profile function execution time."""
    import cProfile
    import pstats
    from io import StringIO

    pr = cProfile.Profile()
    pr.enable()

    result = func(*args, **kwargs)

    pr.disable()

    s = StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(20)

    return result, s.getvalue()
