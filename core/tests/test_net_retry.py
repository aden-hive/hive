"""Tests for framework.net.retry module."""

import pytest

from framework.net.retry import retry_with_backoff


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(succeed, max_retries=3)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await retry_with_backoff(
            flaky, max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,)
        )
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        async def always_fail():
            raise ValueError("always")

        with pytest.raises(ValueError, match="always"):
            await retry_with_backoff(
                always_fail, max_retries=2, base_delay=0.01, retryable_exceptions=(ValueError,)
            )

    @pytest.mark.asyncio
    async def test_non_retryable_exception_not_retried(self):
        call_count = 0

        async def type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            await retry_with_backoff(
                type_error, max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,)
            )
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_zero_retries(self):
        call_count = 0

        async def fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await retry_with_backoff(fail, max_retries=0, retryable_exceptions=(ValueError,))
        assert call_count == 1
