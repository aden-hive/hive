"""
rate limiter for llm provider calls.

provides configurable rate limiting with exponential backoff and jitter
to handle api rate limits gracefully across different providers.
"""

import asyncio
import logging
import random
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RateLimitConfig:
    """configuration for rate limiting."""

    # max retries before giving up
    max_retries: int = 10

    # base delay for exponential backoff (seconds)
    base_delay: float = 2.0

    # max delay cap (seconds) - dont wait longer than this
    max_delay: float = 60.0

    # add random jitter to avoid thundering herd
    jitter: bool = True

    # max jitter as fraction of delay (0.0 to 1.0)
    jitter_factor: float = 0.25


@dataclass
class RateLimitStats:
    """stats for rate limiting."""

    total_requests: int = 0
    retries: int = 0
    rate_limit_hits: int = 0
    empty_response_retries: int = 0
    failed_requests: int = 0


class RateLimiter:
    """
    rate limiter with exponential backoff.

    tracks rate limits per model/provider and provides retry logic
    with configurable backoff and jitter.

    usage:
        limiter = RateLimiter()

        # wrap a function call with retry logic
        result = limiter.with_retry(
            lambda: api.call(model="gpt-4"),
            model="gpt-4",
        )

        # or use as decorator
        @limiter.retry_on_rate_limit
        def my_api_call():
            ...
    """

    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig()
        self._stats: dict[str, RateLimitStats] = defaultdict(RateLimitStats)
        self._last_request_time: dict[str, float] = {}

    def _calculate_backoff(self, attempt: int) -> float:
        """calculate backoff delay with optional jitter."""
        delay = self.config.base_delay * (2**attempt)
        delay = min(delay, self.config.max_delay)

        if self.config.jitter:
            # add random jitter to spread out retries
            jitter_amount = delay * self.config.jitter_factor
            delay = delay + random.uniform(-jitter_amount, jitter_amount)
            delay = max(0.1, delay)  # never go below 0.1s

        return delay

    def with_retry(
        self,
        func: Callable[[], T],
        model: str = "default",
        is_rate_limit_error: Callable[[Exception], bool] | None = None,
        is_empty_response: Callable[[Any], bool] | None = None,
    ) -> T:
        """
        execute a function with retry on rate limit errors.

        args:
            func: function to call
            model: model name for stats tracking
            is_rate_limit_error: check if exception is a rate limit error
            is_empty_response: check if response is empty (treated as rate limit)

        returns:
            result from func

        raises:
            exception from func if max retries exceeded
        """
        stats = self._stats[model]
        stats.total_requests += 1

        for attempt in range(self.config.max_retries + 1):
            try:
                result = func()

                # check for empty response (some apis return 200 with empty on rate limit)
                if is_empty_response and is_empty_response(result):
                    stats.empty_response_retries += 1
                    stats.retries += 1

                    if attempt == self.config.max_retries:
                        logger.error(
                            f"gave up on {model} after {self.config.max_retries + 1} "
                            f"attempts - empty response"
                        )
                        return result

                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        f"{model} returned empty response - retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    time.sleep(delay)
                    continue

                # success
                self._last_request_time[model] = time.time()
                return result

            except Exception as e:
                # check if this is a rate limit error
                is_rate_limit = False
                if is_rate_limit_error:
                    is_rate_limit = is_rate_limit_error(e)
                else:
                    # default: check for common rate limit indicators
                    error_str = str(e).lower()
                    is_rate_limit = "429" in error_str or "rate limit" in error_str

                if is_rate_limit:
                    stats.rate_limit_hits += 1
                    stats.retries += 1

                    if attempt == self.config.max_retries:
                        stats.failed_requests += 1
                        logger.error(
                            f"gave up on {model} after {self.config.max_retries + 1} "
                            f"attempts - rate limit: {e}"
                        )
                        raise

                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        f"{model} rate limited: {e}. retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    time.sleep(delay)
                    continue

                # not a rate limit error, dont retry
                stats.failed_requests += 1
                raise

        # shouldnt get here but just in case
        raise RuntimeError(f"exhausted rate limit retries for {model}")

    async def with_retry_async(
        self,
        func: Callable[[], Any],
        model: str = "default",
        is_rate_limit_error: Callable[[Exception], bool] | None = None,
        is_empty_response: Callable[[Any], bool] | None = None,
    ) -> Any:
        """async version of with_retry."""
        stats = self._stats[model]
        stats.total_requests += 1

        for attempt in range(self.config.max_retries + 1):
            try:
                result = await func()

                if is_empty_response and is_empty_response(result):
                    stats.empty_response_retries += 1
                    stats.retries += 1

                    if attempt == self.config.max_retries:
                        logger.error(
                            f"gave up on {model} after {self.config.max_retries + 1} "
                            f"attempts - empty response"
                        )
                        return result

                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        f"{model} returned empty response - retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue

                self._last_request_time[model] = time.time()
                return result

            except Exception as e:
                is_rate_limit = False
                if is_rate_limit_error:
                    is_rate_limit = is_rate_limit_error(e)
                else:
                    error_str = str(e).lower()
                    is_rate_limit = "429" in error_str or "rate limit" in error_str

                if is_rate_limit:
                    stats.rate_limit_hits += 1
                    stats.retries += 1

                    if attempt == self.config.max_retries:
                        stats.failed_requests += 1
                        logger.error(
                            f"gave up on {model} after {self.config.max_retries + 1} "
                            f"attempts - rate limit: {e}"
                        )
                        raise

                    delay = self._calculate_backoff(attempt)
                    logger.warning(
                        f"{model} rate limited: {e}. retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.config.max_retries})"
                    )
                    await asyncio.sleep(delay)
                    continue

                stats.failed_requests += 1
                raise

        raise RuntimeError(f"exhausted rate limit retries for {model}")

    def get_stats(self, model: str | None = None) -> dict[str, Any]:
        """get rate limiting stats."""
        if model:
            stats = self._stats[model]
            return {
                "model": model,
                "total_requests": stats.total_requests,
                "retries": stats.retries,
                "rate_limit_hits": stats.rate_limit_hits,
                "empty_response_retries": stats.empty_response_retries,
                "failed_requests": stats.failed_requests,
            }

        # return all stats
        return {
            model: {
                "total_requests": stats.total_requests,
                "retries": stats.retries,
                "rate_limit_hits": stats.rate_limit_hits,
                "empty_response_retries": stats.empty_response_retries,
                "failed_requests": stats.failed_requests,
            }
            for model, stats in self._stats.items()
        }

    def reset_stats(self, model: str | None = None) -> None:
        """reset stats for a model or all models."""
        if model:
            self._stats[model] = RateLimitStats()
        else:
            self._stats.clear()


# global default rate limiter
_default_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """get or create the default rate limiter."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RateLimiter()
    return _default_limiter


def with_retry(
    func: Callable[[], T],
    model: str = "default",
    is_rate_limit_error: Callable[[Exception], bool] | None = None,
    is_empty_response: Callable[[Any], bool] | None = None,
) -> T:
    """convenience function using the default rate limiter."""
    return get_rate_limiter().with_retry(func, model, is_rate_limit_error, is_empty_response)
