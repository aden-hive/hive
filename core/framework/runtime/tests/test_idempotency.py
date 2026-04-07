"""Tests for webhook idempotency key support in AgentHost.trigger()."""

import asyncio
import time
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.host.agent_host import AgentHost, AgentRuntimeConfig


def _make_runtime(ttl=300.0, max_keys=10000):
    """Create a minimal AgentRuntime with idempotency cache attributes.

    Uses ``object.__new__`` to skip ``__init__`` and its heavy dependencies
    (storage, LLM, skills) — we only need the cache and config for these tests.
    """
    runtime = object.__new__(AgentHost)
    runtime._config = AgentRuntimeConfig(idempotency_ttl_seconds=ttl, idempotency_max_keys=max_keys)
    runtime._running = True
    runtime._lock = asyncio.Lock()
    runtime._idempotency_keys = OrderedDict()
    runtime._idempotency_times = {}
    runtime._graphs = {}
    runtime._active_graph_id = "primary"
    runtime._graph_id = "primary"
    runtime._streams = {}
    runtime._entry_points = {}
    return runtime


def _make_runtime_with_stream(ttl=300.0, max_keys=10000):
    """Create a mock runtime whose stream.execute() returns unique IDs."""
    runtime = _make_runtime(ttl=ttl, max_keys=max_keys)

    call_count = 0

    async def _fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return f"session-{call_count:04d}"

    stream = MagicMock()
    stream.execute = _fake_execute
    runtime._streams = {"webhook": stream}
    runtime._entry_points = {"webhook": MagicMock()}
    return runtime


class TestIdempotencyConfig:
    """Verify idempotency configuration defaults."""

    def test_default_ttl(self):
        config = AgentRuntimeConfig()
        assert config.idempotency_ttl_seconds == 300.0

    def test_default_max_keys(self):
        config = AgentRuntimeConfig()
        assert config.idempotency_max_keys == 10000

    def test_custom_config(self):
        config = AgentRuntimeConfig(idempotency_ttl_seconds=60.0, idempotency_max_keys=100)
        assert config.idempotency_ttl_seconds == 60.0
        assert config.idempotency_max_keys == 100


class TestIdempotencyCache:
    """Test the idempotency cache and pruning logic directly."""

    def test_cache_stores_and_retrieves_key(self):
        runtime = _make_runtime()
        runtime._idempotency_keys["stripe-evt-123"] = "exec-001"
        runtime._idempotency_times["stripe-evt-123"] = time.time()

        assert runtime._idempotency_keys.get("stripe-evt-123") == "exec-001"

    def test_cache_returns_none_for_unknown_key(self):
        runtime = _make_runtime()
        assert runtime._idempotency_keys.get("unknown") is None

    def test_prune_removes_expired_keys(self):
        runtime = _make_runtime(ttl=0.1)

        runtime._idempotency_keys["old-key"] = "exec-old"
        runtime._idempotency_times["old-key"] = time.time() - 1.0  # expired

        runtime._prune_idempotency_keys()

        assert "old-key" not in runtime._idempotency_keys
        assert "old-key" not in runtime._idempotency_times

    def test_prune_keeps_fresh_keys(self):
        runtime = _make_runtime(ttl=300.0)

        runtime._idempotency_keys["fresh-key"] = "exec-fresh"
        runtime._idempotency_times["fresh-key"] = time.time()

        runtime._prune_idempotency_keys()

        assert "fresh-key" in runtime._idempotency_keys

    def test_prune_respects_max_keys(self):
        runtime = _make_runtime(max_keys=2)

        for i in range(3):
            key = f"key-{i}"
            runtime._idempotency_keys[key] = f"exec-{i}"
            runtime._idempotency_times[key] = time.time()

        runtime._prune_idempotency_keys()

        assert len(runtime._idempotency_keys) == 2
        # Oldest (key-0) should be evicted
        assert "key-0" not in runtime._idempotency_keys
        assert "key-1" in runtime._idempotency_keys
        assert "key-2" in runtime._idempotency_keys

    def test_prune_evicts_fifo(self):
        runtime = _make_runtime(max_keys=1)

        runtime._idempotency_keys["first"] = "exec-1"
        runtime._idempotency_times["first"] = time.time()
        runtime._idempotency_keys["second"] = "exec-2"
        runtime._idempotency_times["second"] = time.time()

        runtime._prune_idempotency_keys()

        assert len(runtime._idempotency_keys) == 1
        assert "second" in runtime._idempotency_keys
        assert "first" not in runtime._idempotency_keys

    def test_mixed_expired_and_max_size(self):
        runtime = _make_runtime(ttl=0.1, max_keys=2)

        # Add expired key
        runtime._idempotency_keys["expired"] = "exec-e"
        runtime._idempotency_times["expired"] = time.time() - 1.0

        # Add fresh keys
        runtime._idempotency_keys["fresh-1"] = "exec-f1"
        runtime._idempotency_times["fresh-1"] = time.time()
        runtime._idempotency_keys["fresh-2"] = "exec-f2"
        runtime._idempotency_times["fresh-2"] = time.time()

        runtime._prune_idempotency_keys()

        assert "expired" not in runtime._idempotency_keys
        assert "fresh-1" in runtime._idempotency_keys
        assert "fresh-2" in runtime._idempotency_keys


class TestTriggerIdempotency:
    """Tests for trigger() idempotency deduplication."""

    def test_trigger_accepts_idempotency_key(self):
        """trigger() accepts idempotency_key as a keyword argument."""
        import inspect

        sig = inspect.signature(AgentHost.trigger)
        assert "idempotency_key" in sig.parameters

    def test_idempotency_key_defaults_to_none(self):
        """idempotency_key defaults to None (backward compatible)."""
        import inspect

        sig = inspect.signature(AgentHost.trigger)
        assert sig.parameters["idempotency_key"].default is None

    def test_trigger_and_wait_accepts_idempotency_key(self):
        """trigger_and_wait() also accepts idempotency_key."""
        import inspect

        sig = inspect.signature(AgentHost.trigger_and_wait)
        assert "idempotency_key" in sig.parameters

    def test_trigger_and_wait_idempotency_key_defaults_to_none(self):
        """trigger_and_wait() idempotency_key defaults to None."""
        import inspect

        sig = inspect.signature(AgentHost.trigger_and_wait)
        assert sig.parameters["idempotency_key"].default is None

    @pytest.mark.asyncio
    async def test_duplicate_key_returns_cached_id(self):
        """Same idempotency key within TTL returns the cached execution ID."""
        runtime = _make_runtime_with_stream()

        first = await runtime.trigger("webhook", {}, idempotency_key="stripe-evt-001")
        second = await runtime.trigger("webhook", {}, idempotency_key="stripe-evt-001")

        assert first == second
        assert first == "session-0001"

    @pytest.mark.asyncio
    async def test_different_keys_produce_different_ids(self):
        """Different idempotency keys start separate executions."""
        runtime = _make_runtime_with_stream()

        id_a = await runtime.trigger("webhook", {}, idempotency_key="evt-aaa")
        id_b = await runtime.trigger("webhook", {}, idempotency_key="evt-bbb")

        assert id_a != id_b
        assert id_a == "session-0001"
        assert id_b == "session-0002"

    @pytest.mark.asyncio
    async def test_none_key_always_starts_new_execution(self):
        """key=None (default) skips dedup — every call starts fresh."""
        runtime = _make_runtime_with_stream()

        id_1 = await runtime.trigger("webhook", {})
        id_2 = await runtime.trigger("webhook", {})

        assert id_1 != id_2
        assert len(runtime._idempotency_keys) == 0  # nothing cached

    @pytest.mark.asyncio
    async def test_expired_key_allows_new_execution(self):
        """After TTL expires, the same key starts a new execution."""
        runtime = _make_runtime_with_stream(ttl=0.1)

        first = await runtime.trigger("webhook", {}, idempotency_key="evt-expire")

        # Backdate the cached timestamp so the key looks expired
        runtime._idempotency_times["evt-expire"] = time.time() - 1.0

        second = await runtime.trigger("webhook", {}, idempotency_key="evt-expire")

        assert first != second
        assert first == "session-0001"
        assert second == "session-0002"

    @pytest.mark.asyncio
    async def test_stream_not_found_does_not_cache(self):
        """If entry point doesn't exist, nothing is cached."""
        runtime = _make_runtime_with_stream()

        with pytest.raises(ValueError, match="not found"):
            await runtime.trigger("nonexistent", {}, idempotency_key="evt-orphan")

        assert "evt-orphan" not in runtime._idempotency_keys

    @pytest.mark.asyncio
    async def test_execute_error_does_not_cache(self):
        """If stream.execute() raises, nothing is cached so retries can go through."""
        runtime = _make_runtime()

        failing_stream = MagicMock()
        failing_stream.execute = AsyncMock(side_effect=RuntimeError("stream not running"))
        runtime._streams = {"webhook": failing_stream}
        runtime._entry_points = {"webhook": MagicMock()}

        with pytest.raises(RuntimeError, match="stream not running"):
            await runtime.trigger("webhook", {}, idempotency_key="evt-123")

        assert "evt-123" not in runtime._idempotency_keys

    @pytest.mark.asyncio
    async def test_cache_holds_real_execution_id(self):
        """Cached value matches the actual execution ID from execute()."""
        runtime = _make_runtime_with_stream()

        exec_id = await runtime.trigger("webhook", {}, idempotency_key="evt-real")

        cached = runtime._idempotency_keys.get("evt-real")
        assert cached == exec_id
        assert cached == "session-0001"
