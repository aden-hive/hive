"""
tests for the llm rate limiter.

tests backoff timing, retry logic, and stats tracking.
"""

from unittest.mock import MagicMock

import pytest

from framework.llm.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    get_rate_limiter,
    with_retry,
)


class TestBackoffCalculation:
    """test backoff delay calculation"""

    def test_exponential_backoff(self):
        config = RateLimitConfig(base_delay=1.0, jitter=False)
        limiter = RateLimiter(config)

        # check exponential growth
        assert limiter._calculate_backoff(0) == 1.0
        assert limiter._calculate_backoff(1) == 2.0
        assert limiter._calculate_backoff(2) == 4.0
        assert limiter._calculate_backoff(3) == 8.0

    def test_max_delay_cap(self):
        config = RateLimitConfig(base_delay=10.0, max_delay=30.0, jitter=False)
        limiter = RateLimiter(config)

        # should cap at max_delay
        assert limiter._calculate_backoff(0) == 10.0
        assert limiter._calculate_backoff(1) == 20.0
        assert limiter._calculate_backoff(2) == 30.0  # capped
        assert limiter._calculate_backoff(3) == 30.0  # still capped

    def test_jitter_adds_variance(self):
        config = RateLimitConfig(base_delay=10.0, jitter=True, jitter_factor=0.5)
        limiter = RateLimiter(config)

        # run multiple times and check for variance
        delays = [limiter._calculate_backoff(0) for _ in range(10)]

        # should have some variance due to jitter
        assert min(delays) != max(delays), "jitter should add variance"

        # should be roughly around base delay
        avg = sum(delays) / len(delays)
        assert 5.0 < avg < 15.0, "average should be near base delay"


class TestRetryLogic:
    """test retry behavior"""

    def test_success_on_first_try(self):
        config = RateLimitConfig(max_retries=3)
        limiter = RateLimiter(config)

        mock_func = MagicMock(return_value="success")

        result = limiter.with_retry(mock_func, model="test")

        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_on_rate_limit(self):
        config = RateLimitConfig(max_retries=3, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        # fail twice then succeed
        mock_func = MagicMock(
            side_effect=[
                Exception("429 rate limit exceeded"),
                Exception("rate limit error"),
                "success",
            ]
        )

        result = limiter.with_retry(mock_func, model="test")

        assert result == "success"
        assert mock_func.call_count == 3

    def test_max_retries_exceeded(self):
        config = RateLimitConfig(max_retries=2, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        # always fail
        mock_func = MagicMock(side_effect=Exception("429 rate limit"))

        with pytest.raises(Exception) as exc:
            limiter.with_retry(mock_func, model="test")

        assert "429" in str(exc.value)
        assert mock_func.call_count == 3  # initial + 2 retries

    def test_non_rate_limit_error_not_retried(self):
        config = RateLimitConfig(max_retries=3)
        limiter = RateLimiter(config)

        # a regular error should not trigger retry
        mock_func = MagicMock(side_effect=ValueError("invalid input"))

        with pytest.raises(ValueError):
            limiter.with_retry(mock_func, model="test")

        assert mock_func.call_count == 1

    def test_custom_rate_limit_check(self):
        config = RateLimitConfig(max_retries=2, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        # custom error that should be treated as rate limit
        class CustomError(Exception):
            pass

        mock_func = MagicMock(side_effect=[CustomError("quota exceeded"), "success"])

        result = limiter.with_retry(
            mock_func,
            model="test",
            is_rate_limit_error=lambda e: isinstance(e, CustomError),
        )

        assert result == "success"
        assert mock_func.call_count == 2


class TestEmptyResponseHandling:
    """test empty response retry logic"""

    def test_empty_response_retried(self):
        config = RateLimitConfig(max_retries=3, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        # return empty then success
        mock_func = MagicMock(
            side_effect=[
                {"content": ""},  # empty
                {"content": ""},  # empty again
                {"content": "success"},
            ]
        )

        result = limiter.with_retry(
            mock_func,
            model="test",
            is_empty_response=lambda r: not r.get("content"),
        )

        assert result["content"] == "success"
        assert mock_func.call_count == 3

    def test_empty_response_max_retries(self):
        config = RateLimitConfig(max_retries=2, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        # always return empty
        mock_func = MagicMock(return_value={"content": ""})

        result = limiter.with_retry(
            mock_func,
            model="test",
            is_empty_response=lambda r: not r.get("content"),
        )

        # should return the empty response after max retries
        assert result["content"] == ""
        assert mock_func.call_count == 3


class TestStatsTracking:
    """test stats are tracked correctly"""

    def test_stats_tracked(self):
        config = RateLimitConfig(max_retries=3, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        # fail once then succeed
        mock_func = MagicMock(side_effect=[Exception("429 rate limit"), "success"])

        limiter.with_retry(mock_func, model="gpt-4")

        stats = limiter.get_stats("gpt-4")
        assert stats["total_requests"] == 1
        assert stats["retries"] == 1
        assert stats["rate_limit_hits"] == 1
        assert stats["failed_requests"] == 0

    def test_failed_request_counted(self):
        config = RateLimitConfig(max_retries=1, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        class RateLimitError(Exception):
            pass

        mock_func = MagicMock(side_effect=RateLimitError("429"))

        with pytest.raises(RateLimitError):
            limiter.with_retry(mock_func, model="gpt-4")

        stats = limiter.get_stats("gpt-4")
        assert stats["failed_requests"] == 1

    def test_stats_per_model(self):
        config = RateLimitConfig(base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        limiter.with_retry(lambda: "a", model="model-a")
        limiter.with_retry(lambda: "b", model="model-b")
        limiter.with_retry(lambda: "c", model="model-a")

        stats_a = limiter.get_stats("model-a")
        stats_b = limiter.get_stats("model-b")

        assert stats_a["total_requests"] == 2
        assert stats_b["total_requests"] == 1

    def test_reset_stats(self):
        limiter = RateLimiter()

        limiter.with_retry(lambda: "x", model="test")
        assert limiter.get_stats("test")["total_requests"] == 1

        limiter.reset_stats("test")
        assert limiter.get_stats("test")["total_requests"] == 0


class TestAsyncRetry:
    """test async retry logic"""

    @pytest.mark.asyncio
    async def test_async_success(self):
        config = RateLimitConfig(max_retries=3)
        limiter = RateLimiter(config)

        async def success_func():
            return "async success"

        result = await limiter.with_retry_async(success_func, model="test")
        assert result == "async success"

    @pytest.mark.asyncio
    async def test_async_retry_on_rate_limit(self):
        config = RateLimitConfig(max_retries=3, base_delay=0.01, jitter=False)
        limiter = RateLimiter(config)

        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("429 rate limit")
            return "success"

        result = await limiter.with_retry_async(flaky_func, model="test")

        assert result == "success"
        assert call_count == 3


class TestGlobalLimiter:
    """test global rate limiter instance"""

    def test_get_rate_limiter_returns_same_instance(self):
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        assert limiter1 is limiter2

    def test_with_retry_convenience_function(self):
        # reset the global limiter
        import framework.llm.rate_limiter as rl

        rl._default_limiter = None

        result = with_retry(lambda: "convenient", model="test")
        assert result == "convenient"
