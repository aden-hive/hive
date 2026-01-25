"""Tests for CodeSandbox timeout enforcement."""

import pytest
import time

from framework.graph.code_sandbox import CodeSandbox, SandboxResult


class TestCodeSandboxTimeout:
    """Test timeout enforcement on all platforms."""

    def test_timeout_on_long_running_code(self):
        """Code exceeding timeout should fail with TimeoutError."""
        sandbox = CodeSandbox(timeout_seconds=1)

        # This loop takes several seconds to complete
        result = sandbox.execute('x = 0\nwhile x < 100000000: x += 1')

        assert result.success is False
        assert result.error is not None
        assert "timed out" in result.error.lower()

    def test_fast_code_completes_successfully(self):
        """Code completing within timeout should succeed."""
        sandbox = CodeSandbox(timeout_seconds=5)

        result = sandbox.execute('x = 1 + 2\nresult = x * 3')

        assert result.success is True
        assert result.error is None
        assert result.variables.get('result') == 9

    def test_timeout_on_expression(self):
        """Expression exceeding timeout should fail."""
        sandbox = CodeSandbox(timeout_seconds=1)

        # Long-running expression (nested loop via list comprehension)
        result = sandbox.execute_expression('[x*y for x in range(10000) for y in range(10000)]')

        assert result.success is False
        assert result.error is not None
        assert "timed out" in result.error.lower()

    def test_fast_expression_completes(self):
        """Expression completing within timeout should succeed."""
        sandbox = CodeSandbox(timeout_seconds=5)

        result = sandbox.execute_expression('1 + 2 + 3')

        assert result.success is True
        assert result.result == 6

    def test_code_validation_still_works(self):
        """Code validation should still block dangerous operations."""
        sandbox = CodeSandbox(timeout_seconds=5)

        # Import should be blocked
        result = sandbox.execute('import os')

        assert result.success is False
        assert "validation failed" in result.error.lower()

    def test_timeout_returns_correct_error_type(self):
        """Timeout should return TimeoutError message."""
        sandbox = CodeSandbox(timeout_seconds=1)

        result = sandbox.execute('x = 0\nwhile x < 100000000: x += 1')

        assert "TimeoutError" in result.error or "timed out" in result.error.lower()
