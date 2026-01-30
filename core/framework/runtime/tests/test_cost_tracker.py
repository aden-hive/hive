"""Tests for the CostTracker module."""

import asyncio
import pytest
from datetime import datetime, timedelta

from framework.runtime.cost_tracker import (
    CostTracker,
    CostEntry,
    CostSummary,
    CostCategory,
    BudgetPolicy,
    BudgetThreshold,
    BudgetAction,
    ModelPricing,
    CircuitBreaker,
    CircuitBreakerState,
    create_cost_tracker,
    DEFAULT_PRICING,
)


class TestModelPricing:
    """Tests for ModelPricing."""

    def test_calculate_cost(self):
        """Test cost calculation with input and output tokens."""
        pricing = ModelPricing(
            model_id="test-model",
            input_cost_per_1k=0.01,
            output_cost_per_1k=0.03,
        )

        # 1000 input, 500 output
        cost = pricing.calculate_cost(1000, 500)
        assert cost == pytest.approx(0.01 + 0.015, rel=1e-6)

    def test_calculate_cost_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        pricing = ModelPricing("test", 0.01, 0.03)
        assert pricing.calculate_cost(0, 0) == 0.0

    def test_default_pricing_exists(self):
        """Test that default pricing is available for common models."""
        assert "claude-3-sonnet" in DEFAULT_PRICING
        assert "gpt-4o" in DEFAULT_PRICING


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state(self):
        """Test initial circuit breaker state."""
        cb = CircuitBreaker()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_execute()

    def test_trip(self):
        """Test tripping the circuit breaker."""
        cb = CircuitBreaker()
        cb.trip()

        assert cb.state == CircuitBreakerState.OPEN
        assert not cb.can_execute()
        assert cb.trip_count == 1

    def test_reset_after_timeout(self):
        """Test circuit breaker resets after timeout."""
        cb = CircuitBreaker(reset_timeout=timedelta(seconds=0))
        cb.trip()

        # With zero timeout, should immediately be able to execute (half-open)
        assert cb.can_execute()
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_record_success_closes(self):
        """Test successful execution closes half-open breaker."""
        cb = CircuitBreaker(reset_timeout=timedelta(seconds=0))
        cb.trip()
        cb.can_execute()  # Transition to half-open

        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_manual_reset(self):
        """Test manual reset of circuit breaker."""
        cb = CircuitBreaker()
        cb.trip()
        cb.reset()

        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.can_execute()


class TestCostEntry:
    """Tests for CostEntry."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        entry = CostEntry(
            timestamp=datetime(2025, 1, 15, 10, 30, 0),
            stream_id="stream-1",
            execution_id="exec-1",
            category=CostCategory.LLM_INPUT,
            amount=0.05,
            model_id="claude-3-sonnet",
            input_tokens=1000,
        )

        result = entry.to_dict()
        assert result["stream_id"] == "stream-1"
        assert result["category"] == "llm_input"
        assert result["amount"] == 0.05


class TestBudgetThreshold:
    """Tests for BudgetThreshold."""

    def test_should_trigger_below_threshold(self):
        """Test threshold not triggered when below amount."""
        threshold = BudgetThreshold(amount=10.0, action=BudgetAction.WARN)
        assert not threshold.should_trigger(5.0)

    def test_should_trigger_at_threshold(self):
        """Test threshold triggered at amount."""
        threshold = BudgetThreshold(amount=10.0, action=BudgetAction.WARN)
        assert threshold.should_trigger(10.0)

    def test_cooldown_prevents_repeated_triggers(self):
        """Test cooldown prevents rapid re-triggering."""
        threshold = BudgetThreshold(
            amount=10.0,
            action=BudgetAction.WARN,
            cooldown=timedelta(minutes=5),
        )

        # First trigger
        assert threshold.should_trigger(10.0)
        threshold.last_triggered = datetime.now()

        # Should not trigger again due to cooldown
        assert not threshold.should_trigger(10.0)


class TestCostTracker:
    """Tests for CostTracker."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh cost tracker for each test."""
        return CostTracker()

    @pytest.mark.asyncio
    async def test_record_llm_usage(self, tracker):
        """Test recording LLM token usage."""
        entry = await tracker.record_llm_usage(
            stream_id="stream-1",
            execution_id="exec-1",
            model_id="claude-3-sonnet",
            input_tokens=1000,
            output_tokens=500,
        )

        assert entry.amount > 0
        assert tracker.get_total_cost() > 0

    @pytest.mark.asyncio
    async def test_record_tool_usage(self, tracker):
        """Test recording tool usage."""
        entry = await tracker.record_tool_usage(
            stream_id="stream-1",
            execution_id="exec-1",
            tool_name="web_search",
            cost=0.01,
        )

        assert entry.amount == 0.01
        assert tracker.get_total_cost() == pytest.approx(0.01, rel=1e-6)

    @pytest.mark.asyncio
    async def test_get_stream_cost(self, tracker):
        """Test getting cost for a specific stream."""
        await tracker.record_llm_usage("stream-1", "exec-1", "claude-3-sonnet", 1000, 500)
        await tracker.record_llm_usage("stream-2", "exec-2", "claude-3-sonnet", 1000, 500)
        await tracker.record_llm_usage("stream-1", "exec-3", "claude-3-sonnet", 1000, 500)

        stream_1_cost = tracker.get_stream_cost("stream-1")
        stream_2_cost = tracker.get_stream_cost("stream-2")

        # Stream 1 has 2 entries, stream 2 has 1
        assert stream_1_cost > stream_2_cost

    @pytest.mark.asyncio
    async def test_get_execution_cost(self, tracker):
        """Test getting cost for a specific execution."""
        await tracker.record_llm_usage("stream-1", "exec-1", "claude-3-sonnet", 1000, 500)
        await tracker.record_tool_usage("stream-1", "exec-1", "tool", 0.01)

        cost = tracker.get_execution_cost("stream-1", "exec-1")
        assert cost > 0.01  # LLM + tool cost

    @pytest.mark.asyncio
    async def test_get_summary(self, tracker):
        """Test getting cost summary."""
        await tracker.record_llm_usage("stream-1", "exec-1", "claude-3-sonnet", 1000, 500)
        await tracker.record_tool_usage("stream-1", "exec-1", "tool", 0.01)

        summary = tracker.get_summary()
        assert summary.total_cost > 0
        assert summary.entry_count >= 2
        assert CostCategory.LLM_INPUT.value in summary.cost_by_category or CostCategory.LLM_OUTPUT.value in summary.cost_by_category
        assert "stream-1" in summary.cost_by_stream

    @pytest.mark.asyncio
    async def test_budget_policy_warning(self, tracker):
        """Test budget warning threshold."""
        tracker.set_agent_budget(max_budget=0.01, warn_at_percent=0.5)

        warnings_triggered = []
        tracker.on_threshold_reached(lambda t, c: warnings_triggered.append((t, c)))

        # Record enough to trigger warning
        await tracker.record_tool_usage("stream-1", "exec-1", "tool", 0.006)

        assert len(warnings_triggered) > 0

    @pytest.mark.asyncio
    async def test_budget_policy_halt(self, tracker):
        """Test budget halt threshold trips circuit breaker."""
        tracker.set_agent_budget(max_budget=0.01)

        # Record enough to exceed budget
        await tracker.record_tool_usage("stream-1", "exec-1", "tool", 0.02)

        assert not tracker.can_execute()

    @pytest.mark.asyncio
    async def test_can_execute_with_budget(self, tracker):
        """Test execution control based on budget."""
        tracker.set_agent_budget(max_budget=1.0)
        assert tracker.can_execute()

        # Trip circuit breaker manually
        tracker._circuit_breaker.trip()
        assert not tracker.can_execute()

    def test_stream_budget(self, tracker):
        """Test stream-level budget configuration."""
        tracker.set_stream_budget("stream-1", 0.50)

        policy = tracker.get_policy("stream", "stream-1")
        assert policy is not None
        assert policy.max_budget == 0.50

    @pytest.mark.asyncio
    async def test_get_entries_with_filter(self, tracker):
        """Test getting entries with filters."""
        await tracker.record_llm_usage("stream-1", "exec-1", "claude-3-sonnet", 100, 50)
        await tracker.record_tool_usage("stream-1", "exec-1", "tool", 0.01)
        await tracker.record_llm_usage("stream-2", "exec-2", "gpt-4o", 100, 50)

        # Filter by stream
        entries = tracker.get_entries(stream_id="stream-1")
        assert all(e.stream_id == "stream-1" for e in entries)

        # Filter by category
        entries = tracker.get_entries(category=CostCategory.TOOL_CALL)
        assert all(e.category == CostCategory.TOOL_CALL for e in entries)

    def test_get_stats(self, tracker):
        """Test getting tracker statistics."""
        stats = tracker.get_stats()

        assert "total_cost" in stats
        assert "circuit_breaker_state" in stats
        assert stats["circuit_breaker_state"] == "closed"

    def test_reset(self, tracker):
        """Test resetting the tracker."""
        tracker._circuit_breaker.trip()
        tracker.reset()

        assert tracker.get_total_cost() == 0
        assert tracker.can_execute()

    def test_custom_pricing(self):
        """Test custom model pricing."""
        custom_pricing = {
            "custom-model": ModelPricing("custom-model", 0.001, 0.002)
        }
        tracker = CostTracker(custom_pricing=custom_pricing)

        pricing = tracker.get_model_pricing("custom-model")
        assert pricing is not None
        assert pricing.input_cost_per_1k == 0.001


class TestCreateCostTracker:
    """Tests for the factory function."""

    def test_create_with_defaults(self):
        """Test creating tracker with defaults."""
        tracker = create_cost_tracker()
        assert tracker is not None
        assert tracker.get_total_cost() == 0

    def test_create_with_budget(self):
        """Test creating tracker with budget."""
        tracker = create_cost_tracker(agent_budget=100.0)

        policy = tracker.get_policy("agent")
        assert policy is not None
        assert policy.max_budget == 100.0

    def test_create_with_custom_pricing(self):
        """Test creating tracker with custom pricing."""
        custom = {"my-model": ModelPricing("my-model", 0.01, 0.02)}
        tracker = create_cost_tracker(custom_pricing=custom)

        pricing = tracker.get_model_pricing("my-model")
        assert pricing is not None


class TestCostSummary:
    """Tests for CostSummary."""

    def test_to_dict(self):
        """Test serialization."""
        summary = CostSummary(
            total_cost=1.50,
            cost_by_category={"llm_input": 0.50, "llm_output": 1.00},
            total_input_tokens=10000,
            total_output_tokens=5000,
            entry_count=10,
        )

        result = summary.to_dict()
        assert result["total_cost"] == 1.50
        assert result["total_input_tokens"] == 10000

    def test_empty_summary(self):
        """Test empty summary defaults."""
        summary = CostSummary()
        assert summary.total_cost == 0.0
        assert summary.entry_count == 0
