"""Fault-tolerant circuit breaker for remote API calls (LLM/MCP).

Provides a stdlib-only thread-safe circuit breaker to gracefully
degrade and fail fast when remote endpoints are unavailable.
"""

import functools
import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"        # Operating normally, requests pass through
    OPEN = "open"            # Failing, requests are blocked
    HALF_OPEN = "half_open"  # Testing recovery, single atomic probe allowed


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open or blocking thundering herd."""

    def __init__(self, message: str, breaker_name: str, state: CircuitState):
        super().__init__(message)
        self.breaker_name = breaker_name
        self.state = state


class CircuitBreaker:
    """A thread-safe state machine for circuit breaking."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exceptions: tuple[type[BaseException], ...] = (Exception,),
    ):
        """
        Initialize the circuit breaker.

        Args:
            name: Identifier for logs and errors.
            failure_threshold: Consecutive failures before tripping to OPEN.
            recovery_timeout: Seconds to wait before transitioning to HALF_OPEN.
            expected_exceptions: Exceptions that count as failures (e.g., 5xx errors).
                Exceptions not in this tuple (e.g. 4xx errors) are treated as successes
                for circuit-breaker semantic purposes because the endpoint is healthy.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions

        self._lock = threading.Lock()
        
        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._probe_in_progress = False

        # Telemetry
        self._total_successes = 0
        self._total_failures = 0
        self._total_trips = 0
        self._total_herd_rejections = 0

    @property
    def state(self) -> CircuitState:
        """Get the current state, evaluating logical transitions over time."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._probe_in_progress = False
                    logger.info("CircuitBreaker[%s] transitioning OPEN -> HALF_OPEN", self.name)
            return self._state

    def to_dict(self) -> dict[str, Any]:
        """Telemetry representation for Grafana / observability."""
        # Call .state first to implicitly trigger time-based transitions
        current_state = self.state
        with self._lock:
            return {
                "name": self.name,
                "state": current_state.value,
                "failure_count": self._failure_count,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "total_trips": self._total_trips,
                "total_herd_rejections": self._total_herd_rejections,
                "probe_in_progress": self._probe_in_progress,
            }

    def __repr__(self) -> str:
        s = self.state
        return f"<CircuitBreaker name={self.name} state={s.value} failures={self._failure_count}>"

    def _on_success(self) -> None:
        """Record success atomically, resetting state if necessary."""
        with self._lock:
            self._total_successes += 1
            if self._state == CircuitState.HALF_OPEN:
                logger.info("CircuitBreaker[%s] probe succeeded. FULLY RECOVERED. HALF_OPEN -> CLOSED", self.name)
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._probe_in_progress = False
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def _on_failure(self, exception: BaseException) -> None:
        """Record failure atomically, advancing state if necessary."""
        with self._lock:
            self._total_failures += 1
            if self._state == CircuitState.HALF_OPEN:
                # Probe failed. Instantly return to OPEN.
                logger.warning("CircuitBreaker[%s] probe failed. HALF_OPEN -> OPEN. Error: %s", self.name, exception)
                self._state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()
                self._probe_in_progress = False
                self._total_trips += 1
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    logger.warning("CircuitBreaker[%s] tripped! CLOSED -> OPEN after %d failures. Error: %s", 
                                   self.name, self._failure_count, exception)
                    self._state = CircuitState.OPEN
                    self._last_failure_time = time.monotonic()
                    self._total_trips += 1

    def _check_and_acquire_permit(self) -> None:
        """
        Check if the call can proceed.
        Raises CircuitOpenError if the breaker is OPEN or blocking a thundering herd.
        """
        # Call .state to perform time-based transitions
        current_state = self.state
        
        with self._lock:
            if current_state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is OPEN. Blocking request.",
                    self.name,
                    self._state,
                )
            
            if current_state == CircuitState.HALF_OPEN:
                if self._probe_in_progress:
                    self._total_herd_rejections += 1
                    raise CircuitOpenError(
                        f"Circuit breaker '{self.name}' is HALF_OPEN and testing recovery. Blocking thundering herd.",
                        self.name,
                        self._state,
                    )
                self._probe_in_progress = True

    def _release_probe_if_unhandled(self) -> None:
        """Safety net for half-open probes that raise unrelated errors."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN and self._probe_in_progress:
                self._probe_in_progress = False

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute a synchronous function through the circuit breaker."""
        self._check_and_acquire_permit()
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except BaseException as e:
            if isinstance(e, self.expected_exceptions):
                self._on_failure(e)
            else:
                # Not a monitored exception (e.g., semantic 4xx error). Treat as successful pass-through.
                self._on_success()
            self._release_probe_if_unhandled()
            raise

    async def acall(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute an asynchronous function through the circuit breaker."""
        self._check_and_acquire_permit()
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except BaseException as e:
            if isinstance(e, self.expected_exceptions):
                self._on_failure(e)
            else:
                self._on_success()
            self._release_probe_if_unhandled()
            raise


def circuit_breaker_sync(breaker: CircuitBreaker):
    """Decorator for synchronous methods."""
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator


def circuit_breaker_async(breaker: CircuitBreaker):
    """Decorator for asynchronous methods."""
    def decorator(func: Callable[..., Any]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.acall(func, *args, **kwargs)
        return wrapper
    return decorator
