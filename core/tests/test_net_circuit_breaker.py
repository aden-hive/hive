"""Tests for framework.net.circuit_breaker module."""

import asyncio

import pytest

from framework.net.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitState


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_stays_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                async with cb:
                    raise ValueError("fail")
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=100)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerError):
            async with cb:
                pass

    @pytest.mark.asyncio
    async def test_half_open_after_recovery(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_recovery_to_closed(self):
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=0.1, success_threshold=1
        )
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        await asyncio.sleep(0.15)
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_excluded_exceptions_dont_count(self):
        cb = CircuitBreaker("test", failure_threshold=1, excluded_exceptions=(ValueError,))
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("excluded")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_as_decorator(self):
        cb = CircuitBreaker("test", failure_threshold=3)

        @cb
        async def my_func() -> str:
            return "ok"

        result = await my_func()
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_state_change_callback(self):
        transitions: list[tuple[CircuitState, CircuitState]] = []

        def on_change(old: CircuitState, new: CircuitState):
            transitions.append((old, new))

        cb = CircuitBreaker("test", failure_threshold=1, on_state_change=on_change)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("fail")
        assert len(transitions) == 1
        assert transitions[0] == (CircuitState.CLOSED, CircuitState.OPEN)

    def test_stats(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        stats = cb.stats()
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
