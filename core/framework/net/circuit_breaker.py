"""
Circuit breaker pattern for network calls — prevents cascading failures
when external services (GitHub API, Sentry, LLM providers) are down.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any

logger = logging.getLogger("framework.net.circuit_breaker")


class CircuitState(StrEnum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when the circuit is open and calls are rejected."""

    def __init__(self, breaker_name: str, until: float):
        self.breaker_name = breaker_name
        self.until = until
        remaining = max(0, until - time.monotonic())
        super().__init__(
            f"Circuit '{breaker_name}' is OPEN. Retry in {remaining:.1f}s"
        )


class CircuitBreaker:
    """
    Async-compatible circuit breaker.

    Usage::

        breaker = CircuitBreaker("github-api", failure_threshold=5, recovery_timeout=60)

        async with breaker:
            result = await call_github_api()

        # Or as a decorator:
        @breaker
        async def call_github_api():
            ...
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
        success_threshold: int = 2,
        excluded_exceptions: tuple[type[Exception], ...] = (),
        on_state_change: Callable[[CircuitState, CircuitState], None] | None = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self.excluded_exceptions = excluded_exceptions
        self.on_state_change = on_state_change

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    def _transition(self, new_state: CircuitState) -> None:
        old_state = self._state
        if old_state != new_state:
            logger.info(
                "Circuit '%s': %s -> %s",
                self.name,
                old_state.value,
                new_state.value,
            )
            self._state = new_state
            if self.on_state_change:
                try:
                    self.on_state_change(old_state, new_state)
                except Exception:
                    logger.exception("on_state_change callback error")

    def _record_success(self) -> None:
        self._failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._transition(CircuitState.CLOSED)
                self._success_count = 0
                self._half_open_calls = 0

    def _record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        self._success_count = 0

        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
            self._half_open_calls = 0
        elif self._failure_count >= self.failure_threshold:
            self._transition(CircuitState.OPEN)

    async def __aenter__(self) -> CircuitBreaker:
        async with self._lock:
            state = self.state
            if state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    self.name,
                    self._last_failure_time + self.recovery_timeout,
                )
            if state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerError(
                        self.name,
                        self._last_failure_time + self.recovery_timeout,
                    )
                self._half_open_calls += 1
                self._transition(CircuitState.HALF_OPEN)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        async with self._lock:
            if exc_type is None:
                self._record_success()
            elif exc_type and not issubclass(exc_type, self.excluded_exceptions):
                self._record_failure()
        return False

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """Use as a decorator."""

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async with self:
                return await func(*args, **kwargs)

        return wrapper

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self._transition(CircuitState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }
