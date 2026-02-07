"""Integration tests for Hive framework infrastructure.

Tests all Phase 1-3 modules to ensure they work correctly together.
"""

import asyncio
import pytest


class TestNodePackage:
    """Test the refactored node package."""

    def test_all_imports(self):
        """All node classes should be importable."""
        from framework.graph.node import (
            NodeSpec,
            SharedMemory,
            NodeContext,
            NodeResult,
            NodeProtocol,
            LLMNode,
            RouterNode,
            FunctionNode,
            MemoryWriteError,
            find_json_object,
            fix_unescaped_newlines_in_json,
        )
        assert NodeSpec is not None
        assert SharedMemory is not None
        assert LLMNode is not None

    def test_shared_memory_basic(self):
        """SharedMemory should support basic read/write."""
        from framework.graph.node import SharedMemory

        memory = SharedMemory()
        memory.write("key1", "value1")
        assert memory.read("key1") == "value1"
        assert memory.read("nonexistent") is None

    def test_shared_memory_permissions(self):
        """SharedMemory permissions should be enforced."""
        from framework.graph.node import SharedMemory

        memory = SharedMemory()
        memory.write("allowed", "value")
        memory.write("blocked", "secret")

        scoped = memory.with_permissions(read_keys=["allowed"], write_keys=["allowed"])
        assert scoped.read("allowed") == "value"

        with pytest.raises(PermissionError):
            scoped.read("blocked")

    def test_memory_write_error(self):
        """MemoryWriteError should be raised for suspicious content."""
        from framework.graph.node import SharedMemory, MemoryWriteError

        memory = SharedMemory()
        suspicious = "def foo():\n    pass\n" * 500  # Long code-like content

        with pytest.raises(MemoryWriteError):
            memory.write("key", suspicious, validate=True)

        # Should work with validate=False
        memory.write("key", suspicious, validate=False)
        assert "def foo" in memory.read("key")


class TestErrorHierarchy:
    """Test the error hierarchy."""

    def test_error_inheritance(self):
        """All errors should inherit from HiveError."""
        from framework.errors import (
            HiveError,
            GraphError,
            NodeError,
            LLMError,
            ExecutionError,
        )

        assert issubclass(GraphError, HiveError)
        assert issubclass(NodeError, HiveError)
        assert issubclass(LLMError, HiveError)
        assert issubclass(ExecutionError, HiveError)

    def test_error_codes(self):
        """Errors should have error codes."""
        from framework.errors import NodeInputError, LLMRateLimitError, ErrorContext

        err = NodeInputError("test", context=ErrorContext(node_id="test_node"))
        assert err.error_code == "NODE_INPUT_ERROR"
        assert err.context.node_id == "test_node"

        rate_err = LLMRateLimitError("rate limited")
        assert rate_err.error_code == "LLM_RATE_LIMIT"
        assert rate_err.retry_allowed == True  # Rate limit errors are retryable


class TestLogging:
    """Test structured logging."""

    def test_configure_and_get_logger(self):
        """Should configure and return a structured logger."""
        from framework.logging import configure_logging, get_logger

        configure_logging(level="DEBUG", json_format=False)
        logger = get_logger("test")
        assert logger is not None

    def test_structured_logging(self):
        """Logger should accept key-value extra fields."""
        from framework.logging import get_logger

        logger = get_logger("test_structured")
        # Should not raise
        logger.info("Test message", key1="value1", key2=123)


class TestCache:
    """Test caching layer."""

    @pytest.mark.asyncio
    async def test_lru_cache(self):
        """LRU cache should work correctly."""
        from framework.cache import LRUCache

        cache = LRUCache(max_size=3)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.set("c", 3)

        entry = await cache.get("a")
        assert entry is not None
        assert entry.value == 1

        # Add one more to trigger eviction
        await cache.set("d", 4)

        # "b" should be evicted (LRU)
        entry_b = await cache.get("b")
        assert entry_b is None

    @pytest.mark.asyncio
    async def test_cache_key_generation(self):
        """Cache should generate consistent keys."""
        from framework.cache import Cache

        key1 = Cache.llm_key("claude-3", [{"role": "user", "content": "hello"}])
        key2 = Cache.llm_key("claude-3", [{"role": "user", "content": "hello"}])
        key3 = Cache.llm_key("claude-3", [{"role": "user", "content": "world"}])

        assert key1 == key2  # Same inputs = same key
        assert key1 != key3  # Different inputs = different key


class TestRateLimiting:
    """Test rate limiting."""

    def test_token_bucket(self):
        """Token bucket should manage tokens correctly."""
        from framework.ratelimit import TokenBucket

        bucket = TokenBucket(capacity=10, refill_rate=1.0)

        # Should start with full capacity
        assert bucket.try_acquire(5)
        assert bucket.try_acquire(5)
        assert not bucket.try_acquire(1)  # Empty

    @pytest.mark.asyncio
    async def test_rate_limiter_acquire(self):
        """Rate limiter should allow acquiring within limits."""
        from framework.ratelimit import RateLimiter, RateLimitConfig

        limiter = RateLimiter({
            "test_provider": {
                "default": RateLimitConfig(requests_per_minute=60)
            }
        })

        # Should succeed immediately
        async with await limiter.acquire("test_provider", timeout=1.0):
            pass


class TestTelemetry:
    """Test OpenTelemetry integration."""

    def test_init_without_otel(self):
        """Telemetry should work without OpenTelemetry installed."""
        from framework.telemetry import init_telemetry, get_tracer, get_meter

        # Should not raise even without OpenTelemetry
        tracer = get_tracer()
        meter = get_meter()

        assert tracer is not None
        assert meter is not None

    def test_noop_span(self):
        """NoOp span should work as context manager."""
        from framework.telemetry import get_tracer

        tracer = get_tracer()
        with tracer.start_as_current_span("test"):
            pass


class TestHealth:
    """Test health checks."""

    @pytest.mark.asyncio
    async def test_health_checker(self):
        """Health checker should run registered checks."""
        from framework.health import HealthChecker, HealthStatus, CheckResult

        checker = HealthChecker()

        # Register a simple check
        def simple_check():
            return CheckResult(name="simple", status=HealthStatus.HEALTHY)

        checker.register("simple", simple_check)

        report = await checker.check_all()
        assert report.is_healthy
        assert len(report.checks) == 1

    @pytest.mark.asyncio
    async def test_liveness_probe(self):
        """Liveness probe should always return healthy."""
        from framework.health import HealthChecker

        checker = HealthChecker()
        report = await checker.liveness()
        assert report.is_healthy


class TestIntegration:
    """Test integration between modules."""

    def test_framework_exports(self):
        """Framework package should export all new infrastructure."""
        import framework

        # Phase 1
        assert hasattr(framework, "HiveError")
        assert hasattr(framework, "get_logger")

        # Phase 2
        assert hasattr(framework, "Cache")
        assert hasattr(framework, "RateLimiter")

        # Phase 3
        assert hasattr(framework, "get_tracer")
        assert hasattr(framework, "HealthChecker")

    def test_executor_imports_node_package(self):
        """Executor should import from new node package."""
        from framework.graph.executor import GraphExecutor
        from framework.graph.node import NodeSpec, SharedMemory

        assert GraphExecutor is not None
        assert NodeSpec is not None
        assert SharedMemory is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
