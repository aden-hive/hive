"""
Cost Tracker - Financial management and budget control for agent executions.

Implements the "Financial Circuit Breaker" pattern mentioned in Aden's
product description, enabling:
- Per-execution cost tracking
- Per-stream/entry-point budgets
- Agent-level spending limits
- Automatic cost-based throttling and halting
- Real-time cost alerts via EventBus
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)


class BudgetAction(str, Enum):
    """Actions to take when budget thresholds are reached."""
    WARN = "warn"          # Emit warning event, continue execution
    THROTTLE = "throttle"  # Slow down execution rate
    HALT = "halt"          # Stop execution immediately


class CostCategory(str, Enum):
    """Categories of costs for tracking."""
    LLM_INPUT = "llm_input"      # Input token costs
    LLM_OUTPUT = "llm_output"    # Output token costs
    TOOL_CALL = "tool_call"      # Tool execution costs
    EMBEDDING = "embedding"      # Embedding generation costs
    OTHER = "other"              # Miscellaneous costs


@dataclass
class ModelPricing:
    """Pricing configuration for an LLM model."""
    model_id: str
    input_cost_per_1k: float   # Cost per 1000 input tokens
    output_cost_per_1k: float  # Cost per 1000 output tokens

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate total cost for token usage."""
        input_cost = (input_tokens / 1000) * self.input_cost_per_1k
        output_cost = (output_tokens / 1000) * self.output_cost_per_1k
        return input_cost + output_cost


# Default pricing for common models (as of early 2025)
DEFAULT_PRICING: dict[str, ModelPricing] = {
    "claude-3-opus": ModelPricing("claude-3-opus", 0.015, 0.075),
    "claude-3-sonnet": ModelPricing("claude-3-sonnet", 0.003, 0.015),
    "claude-3-haiku": ModelPricing("claude-3-haiku", 0.00025, 0.00125),
    "claude-3-5-sonnet": ModelPricing("claude-3-5-sonnet", 0.003, 0.015),
    "claude-3-5-haiku": ModelPricing("claude-3-5-haiku", 0.0008, 0.004),
    "gpt-4o": ModelPricing("gpt-4o", 0.0025, 0.01),
    "gpt-4o-mini": ModelPricing("gpt-4o-mini", 0.00015, 0.0006),
    "gpt-4-turbo": ModelPricing("gpt-4-turbo", 0.01, 0.03),
}


@dataclass
class CostEntry:
    """A single cost entry."""
    timestamp: datetime
    stream_id: str
    execution_id: str
    category: CostCategory
    amount: float
    model_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_name: str | None = None
    node_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "stream_id": self.stream_id,
            "execution_id": self.execution_id,
            "category": self.category.value,
            "amount": self.amount,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_name": self.tool_name,
            "node_id": self.node_id,
            "metadata": self.metadata,
        }


@dataclass
class BudgetThreshold:
    """A budget threshold that triggers an action."""
    amount: float              # Threshold amount in dollars
    action: BudgetAction       # Action to take when reached
    window: timedelta | None = None  # Optional time window (rolling budget)
    cooldown: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    last_triggered: datetime | None = None

    def should_trigger(self, current_spend: float) -> bool:
        """Check if this threshold should trigger."""
        if current_spend < self.amount:
            return False

        # Check cooldown
        if self.last_triggered:
            if datetime.now() - self.last_triggered < self.cooldown:
                return False

        return True


@dataclass
class BudgetPolicy:
    """Budget policy for a scope (agent, stream, or execution)."""
    policy_id: str
    scope: str  # "agent", "stream", or "execution"
    scope_id: str | None = None  # Specific ID if scoped to stream/execution
    max_budget: float | None = None  # Hard limit
    thresholds: list[BudgetThreshold] = field(default_factory=list)
    enabled: bool = True

    @classmethod
    def create_default_agent_policy(cls, max_budget: float = 100.0) -> "BudgetPolicy":
        """Create a default agent-level policy."""
        return cls(
            policy_id="default_agent",
            scope="agent",
            max_budget=max_budget,
            thresholds=[
                BudgetThreshold(amount=max_budget * 0.5, action=BudgetAction.WARN),
                BudgetThreshold(amount=max_budget * 0.8, action=BudgetAction.WARN),
                BudgetThreshold(amount=max_budget * 0.95, action=BudgetAction.THROTTLE),
                BudgetThreshold(amount=max_budget, action=BudgetAction.HALT),
            ],
        )


@dataclass
class CostSummary:
    """Summary of costs for a scope."""
    total_cost: float = 0.0
    cost_by_category: dict[str, float] = field(default_factory=dict)
    cost_by_model: dict[str, float] = field(default_factory=dict)
    cost_by_stream: dict[str, float] = field(default_factory=dict)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    entry_count: int = 0
    first_entry: datetime | None = None
    last_entry: datetime | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "total_cost": self.total_cost,
            "cost_by_category": self.cost_by_category,
            "cost_by_model": self.cost_by_model,
            "cost_by_stream": self.cost_by_stream,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "entry_count": self.entry_count,
            "first_entry": self.first_entry.isoformat() if self.first_entry else None,
            "last_entry": self.last_entry.isoformat() if self.last_entry else None,
        }


class CircuitBreakerState(str, Enum):
    """State of the cost circuit breaker."""
    CLOSED = "closed"    # Normal operation
    OPEN = "open"        # Tripped - blocking executions
    HALF_OPEN = "half_open"  # Testing if safe to resume


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for cost-based protection.

    Prevents runaway costs by automatically stopping executions
    when spending exceeds thresholds.
    """
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    trip_threshold: float = 0.0
    reset_timeout: timedelta = field(default_factory=lambda: timedelta(minutes=15))
    tripped_at: datetime | None = None
    trip_count: int = 0

    def trip(self) -> None:
        """Trip the circuit breaker."""
        self.state = CircuitBreakerState.OPEN
        self.tripped_at = datetime.now()
        self.trip_count += 1
        logger.warning(f"Circuit breaker tripped! Trip count: {self.trip_count}")

    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # Check if enough time has passed to try half-open
            if self.tripped_at and datetime.now() - self.tripped_at > self.reset_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                return True
            return False

        # Half-open: allow single execution to test
        return True

    def record_success(self) -> None:
        """Record successful execution (for half-open state)."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.tripped_at = None
            logger.info("Circuit breaker reset to closed state")

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.state = CircuitBreakerState.CLOSED
        self.tripped_at = None


class CostTracker:
    """
    Tracks costs across all agent executions and enforces budget policies.

    Features:
    - Real-time cost tracking per execution, stream, and agent
    - Budget policies with configurable thresholds and actions
    - Circuit breaker pattern for runaway cost protection
    - Integration with EventBus for cost alerts
    - Historical cost analysis

    Example:
        tracker = CostTracker(event_bus=event_bus)

        # Configure budget
        tracker.set_agent_budget(max_budget=50.0)

        # Record LLM usage
        tracker.record_llm_usage(
            stream_id="webhook",
            execution_id="exec_123",
            model_id="claude-3-sonnet",
            input_tokens=1000,
            output_tokens=500,
        )

        # Check if execution is allowed
        if tracker.can_execute("webhook", "exec_456"):
            # Proceed with execution
            pass

        # Get cost summary
        summary = tracker.get_summary()
        print(f"Total spend: ${summary.total_cost:.4f}")
    """

    def __init__(
        self,
        event_bus: "EventBus | None" = None,
        custom_pricing: dict[str, ModelPricing] | None = None,
        max_entries: int = 10000,
    ):
        """
        Initialize cost tracker.

        Args:
            event_bus: Optional event bus for publishing cost alerts
            custom_pricing: Custom model pricing overrides
            max_entries: Maximum cost entries to keep in memory
        """
        self._event_bus = event_bus
        self._pricing = {**DEFAULT_PRICING}
        if custom_pricing:
            self._pricing.update(custom_pricing)

        self._max_entries = max_entries
        self._entries: list[CostEntry] = []
        self._policies: dict[str, BudgetPolicy] = {}
        self._circuit_breaker = CircuitBreaker()
        self._lock = asyncio.Lock()

        # Throttle state
        self._throttle_active = False
        self._throttle_delay: float = 0.0

        # Callbacks for budget events
        self._on_threshold_reached: list[Callable] = []
        self._on_budget_exceeded: list[Callable] = []

    # === PRICING CONFIGURATION ===

    def set_model_pricing(self, model_id: str, pricing: ModelPricing) -> None:
        """Set or update pricing for a model."""
        self._pricing[model_id] = pricing

    def get_model_pricing(self, model_id: str) -> ModelPricing | None:
        """Get pricing for a model."""
        # Try exact match first
        if model_id in self._pricing:
            return self._pricing[model_id]

        # Try prefix matching for versioned models
        for key, pricing in self._pricing.items():
            if model_id.startswith(key) or key.startswith(model_id):
                return pricing

        return None

    # === BUDGET POLICY MANAGEMENT ===

    def set_policy(self, policy: BudgetPolicy) -> None:
        """Add or update a budget policy."""
        key = f"{policy.scope}:{policy.scope_id or 'default'}"
        self._policies[key] = policy

        # Update circuit breaker if this is an agent-level policy with halt threshold
        if policy.scope == "agent" and policy.max_budget:
            self._circuit_breaker.trip_threshold = policy.max_budget

    def get_policy(self, scope: str, scope_id: str | None = None) -> BudgetPolicy | None:
        """Get a budget policy by scope."""
        key = f"{scope}:{scope_id or 'default'}"
        return self._policies.get(key)

    def set_agent_budget(
        self,
        max_budget: float,
        warn_at_percent: float = 0.8,
        throttle_at_percent: float = 0.95,
    ) -> None:
        """
        Convenience method to set agent-level budget with standard thresholds.

        Args:
            max_budget: Maximum budget in dollars
            warn_at_percent: Percentage at which to warn (default 80%)
            throttle_at_percent: Percentage at which to throttle (default 95%)
        """
        policy = BudgetPolicy(
            policy_id="agent_budget",
            scope="agent",
            max_budget=max_budget,
            thresholds=[
                BudgetThreshold(
                    amount=max_budget * warn_at_percent,
                    action=BudgetAction.WARN,
                ),
                BudgetThreshold(
                    amount=max_budget * throttle_at_percent,
                    action=BudgetAction.THROTTLE,
                ),
                BudgetThreshold(
                    amount=max_budget,
                    action=BudgetAction.HALT,
                ),
            ],
        )
        self.set_policy(policy)

    def set_stream_budget(self, stream_id: str, max_budget: float) -> None:
        """Set budget limit for a specific stream/entry point."""
        policy = BudgetPolicy(
            policy_id=f"stream_{stream_id}",
            scope="stream",
            scope_id=stream_id,
            max_budget=max_budget,
            thresholds=[
                BudgetThreshold(amount=max_budget * 0.8, action=BudgetAction.WARN),
                BudgetThreshold(amount=max_budget, action=BudgetAction.HALT),
            ],
        )
        self.set_policy(policy)

    # === COST RECORDING ===

    async def record_llm_usage(
        self,
        stream_id: str,
        execution_id: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostEntry:
        """
        Record LLM token usage and calculate cost.

        Args:
            stream_id: Stream that made the call
            execution_id: Execution ID
            model_id: Model used
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            node_id: Optional node that made the call
            metadata: Additional metadata

        Returns:
            The created cost entry
        """
        # Get pricing
        pricing = self.get_model_pricing(model_id)
        if pricing:
            cost = pricing.calculate_cost(input_tokens, output_tokens)
        else:
            # Default to conservative estimate if model unknown
            cost = (input_tokens + output_tokens * 3) / 1000 * 0.01
            logger.warning(f"Unknown model {model_id}, using default pricing")

        # Create entries for input and output separately for detailed tracking
        input_entry = CostEntry(
            timestamp=datetime.now(),
            stream_id=stream_id,
            execution_id=execution_id,
            category=CostCategory.LLM_INPUT,
            amount=pricing.calculate_cost(input_tokens, 0) if pricing else cost * 0.25,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=0,
            node_id=node_id,
            metadata=metadata or {},
        )

        output_entry = CostEntry(
            timestamp=datetime.now(),
            stream_id=stream_id,
            execution_id=execution_id,
            category=CostCategory.LLM_OUTPUT,
            amount=pricing.calculate_cost(0, output_tokens) if pricing else cost * 0.75,
            model_id=model_id,
            input_tokens=0,
            output_tokens=output_tokens,
            node_id=node_id,
            metadata=metadata or {},
        )

        await self._add_entry(input_entry)
        await self._add_entry(output_entry)

        # Return combined entry for convenience
        return CostEntry(
            timestamp=datetime.now(),
            stream_id=stream_id,
            execution_id=execution_id,
            category=CostCategory.LLM_OUTPUT,  # Primary category
            amount=cost,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            node_id=node_id,
            metadata=metadata or {},
        )

    async def record_tool_usage(
        self,
        stream_id: str,
        execution_id: str,
        tool_name: str,
        cost: float = 0.0,
        node_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostEntry:
        """
        Record tool execution cost.

        Args:
            stream_id: Stream that made the call
            execution_id: Execution ID
            tool_name: Name of the tool
            cost: Cost of the tool call (if applicable)
            node_id: Optional node that made the call
            metadata: Additional metadata

        Returns:
            The created cost entry
        """
        entry = CostEntry(
            timestamp=datetime.now(),
            stream_id=stream_id,
            execution_id=execution_id,
            category=CostCategory.TOOL_CALL,
            amount=cost,
            tool_name=tool_name,
            node_id=node_id,
            metadata=metadata or {},
        )

        await self._add_entry(entry)
        return entry

    async def record_custom_cost(
        self,
        stream_id: str,
        execution_id: str,
        category: CostCategory,
        amount: float,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostEntry:
        """
        Record a custom cost entry.

        Args:
            stream_id: Stream ID
            execution_id: Execution ID
            category: Cost category
            amount: Cost amount
            description: Optional description
            metadata: Additional metadata

        Returns:
            The created cost entry
        """
        entry = CostEntry(
            timestamp=datetime.now(),
            stream_id=stream_id,
            execution_id=execution_id,
            category=category,
            amount=amount,
            metadata={**(metadata or {}), "description": description} if description else (metadata or {}),
        )

        await self._add_entry(entry)
        return entry

    async def _add_entry(self, entry: CostEntry) -> None:
        """Add a cost entry and check budget thresholds."""
        async with self._lock:
            self._entries.append(entry)

            # Trim old entries if needed
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]

        # Check budget thresholds
        await self._check_thresholds(entry.stream_id, entry.execution_id)

    async def _check_thresholds(self, stream_id: str, execution_id: str) -> None:
        """Check all relevant budget thresholds."""
        # Get current costs
        agent_cost = self.get_total_cost()
        stream_cost = self.get_stream_cost(stream_id)
        execution_cost = self.get_execution_cost(stream_id, execution_id)

        # Check agent-level policy
        agent_policy = self.get_policy("agent")
        if agent_policy and agent_policy.enabled:
            await self._check_policy_thresholds(
                agent_policy, agent_cost, stream_id, execution_id
            )

        # Check stream-level policy
        stream_policy = self.get_policy("stream", stream_id)
        if stream_policy and stream_policy.enabled:
            await self._check_policy_thresholds(
                stream_policy, stream_cost, stream_id, execution_id
            )

    async def _check_policy_thresholds(
        self,
        policy: BudgetPolicy,
        current_cost: float,
        stream_id: str,
        execution_id: str,
    ) -> None:
        """Check thresholds for a specific policy."""
        for threshold in policy.thresholds:
            if threshold.should_trigger(current_cost):
                threshold.last_triggered = datetime.now()
                await self._handle_threshold_action(
                    threshold, current_cost, policy, stream_id, execution_id
                )

    async def _handle_threshold_action(
        self,
        threshold: BudgetThreshold,
        current_cost: float,
        policy: BudgetPolicy,
        stream_id: str,
        execution_id: str,
    ) -> None:
        """Handle a triggered threshold action."""
        logger.info(
            f"Budget threshold triggered: {threshold.action.value} at ${threshold.amount:.2f} "
            f"(current: ${current_cost:.4f})"
        )

        if threshold.action == BudgetAction.WARN:
            # Emit warning event
            if self._event_bus:
                await self._emit_cost_warning(
                    stream_id, execution_id, current_cost, threshold.amount, policy
                )
            for callback in self._on_threshold_reached:
                callback(threshold, current_cost)

        elif threshold.action == BudgetAction.THROTTLE:
            # Activate throttling
            self._throttle_active = True
            self._throttle_delay = 1.0  # 1 second delay between executions
            if self._event_bus:
                await self._emit_cost_throttle(
                    stream_id, execution_id, current_cost, threshold.amount
                )

        elif threshold.action == BudgetAction.HALT:
            # Trip the circuit breaker
            self._circuit_breaker.trip()
            if self._event_bus:
                await self._emit_cost_halt(
                    stream_id, execution_id, current_cost, threshold.amount
                )
            for callback in self._on_budget_exceeded:
                callback(current_cost, threshold.amount)

    # === EXECUTION CONTROL ===

    def can_execute(self, stream_id: str | None = None, execution_id: str | None = None) -> bool:
        """
        Check if execution is allowed based on budget constraints.

        Args:
            stream_id: Optional stream to check
            execution_id: Optional execution to check

        Returns:
            True if execution is allowed
        """
        # Check circuit breaker first
        if not self._circuit_breaker.can_execute():
            logger.warning("Execution blocked by circuit breaker")
            return False

        # Check stream-level budget if specified
        if stream_id:
            stream_policy = self.get_policy("stream", stream_id)
            if stream_policy and stream_policy.max_budget:
                stream_cost = self.get_stream_cost(stream_id)
                if stream_cost >= stream_policy.max_budget:
                    logger.warning(f"Stream {stream_id} budget exceeded")
                    return False

        return True

    async def apply_throttle(self) -> None:
        """Apply throttle delay if active."""
        if self._throttle_active and self._throttle_delay > 0:
            await asyncio.sleep(self._throttle_delay)

    def record_execution_success(self) -> None:
        """Record successful execution (for circuit breaker)."""
        self._circuit_breaker.record_success()

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker."""
        self._circuit_breaker.reset()
        self._throttle_active = False
        self._throttle_delay = 0.0
        logger.info("Circuit breaker and throttle manually reset")

    # === COST QUERIES ===

    def get_total_cost(self) -> float:
        """Get total cost across all executions."""
        return sum(e.amount for e in self._entries)

    def get_stream_cost(self, stream_id: str) -> float:
        """Get total cost for a specific stream."""
        return sum(e.amount for e in self._entries if e.stream_id == stream_id)

    def get_execution_cost(self, stream_id: str, execution_id: str) -> float:
        """Get total cost for a specific execution."""
        return sum(
            e.amount for e in self._entries
            if e.stream_id == stream_id and e.execution_id == execution_id
        )

    def get_cost_in_window(self, window: timedelta) -> float:
        """Get cost within a time window."""
        cutoff = datetime.now() - window
        return sum(e.amount for e in self._entries if e.timestamp >= cutoff)

    def get_summary(
        self,
        stream_id: str | None = None,
        execution_id: str | None = None,
        since: datetime | None = None,
    ) -> CostSummary:
        """
        Get a cost summary with optional filtering.

        Args:
            stream_id: Filter by stream
            execution_id: Filter by execution
            since: Only include entries after this time

        Returns:
            Cost summary
        """
        entries = self._entries

        # Apply filters
        if stream_id:
            entries = [e for e in entries if e.stream_id == stream_id]
        if execution_id:
            entries = [e for e in entries if e.execution_id == execution_id]
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        if not entries:
            return CostSummary()

        summary = CostSummary(
            total_cost=sum(e.amount for e in entries),
            entry_count=len(entries),
            first_entry=min(e.timestamp for e in entries),
            last_entry=max(e.timestamp for e in entries),
        )

        # Aggregate by category
        for entry in entries:
            cat = entry.category.value
            summary.cost_by_category[cat] = summary.cost_by_category.get(cat, 0) + entry.amount

            if entry.model_id:
                summary.cost_by_model[entry.model_id] = (
                    summary.cost_by_model.get(entry.model_id, 0) + entry.amount
                )

            summary.cost_by_stream[entry.stream_id] = (
                summary.cost_by_stream.get(entry.stream_id, 0) + entry.amount
            )

            summary.total_input_tokens += entry.input_tokens
            summary.total_output_tokens += entry.output_tokens

        return summary

    def get_entries(
        self,
        stream_id: str | None = None,
        execution_id: str | None = None,
        category: CostCategory | None = None,
        limit: int = 100,
    ) -> list[CostEntry]:
        """
        Get cost entries with optional filtering.

        Args:
            stream_id: Filter by stream
            execution_id: Filter by execution
            category: Filter by category
            limit: Maximum entries to return

        Returns:
            List of cost entries (most recent first)
        """
        entries = self._entries[::-1]  # Reverse for most recent first

        if stream_id:
            entries = [e for e in entries if e.stream_id == stream_id]
        if execution_id:
            entries = [e for e in entries if e.execution_id == execution_id]
        if category:
            entries = [e for e in entries if e.category == category]

        return entries[:limit]

    # === EVENT EMISSION ===

    async def _emit_cost_warning(
        self,
        stream_id: str,
        execution_id: str,
        current_cost: float,
        threshold: float,
        policy: BudgetPolicy,
    ) -> None:
        """Emit cost warning event."""
        if self._event_bus:
            await self._event_bus.emit_cost_alert(
                stream_id=stream_id,
                execution_id=execution_id,
                alert_type="warning",
                current_cost=current_cost,
                threshold=threshold,
                policy_id=policy.policy_id,
            )

    async def _emit_cost_throttle(
        self,
        stream_id: str,
        execution_id: str,
        current_cost: float,
        threshold: float,
    ) -> None:
        """Emit cost throttle event."""
        if self._event_bus:
            await self._event_bus.emit_cost_alert(
                stream_id=stream_id,
                execution_id=execution_id,
                alert_type="throttle",
                current_cost=current_cost,
                threshold=threshold,
            )

    async def _emit_cost_halt(
        self,
        stream_id: str,
        execution_id: str,
        current_cost: float,
        threshold: float,
    ) -> None:
        """Emit cost halt event."""
        if self._event_bus:
            await self._event_bus.emit_cost_alert(
                stream_id=stream_id,
                execution_id=execution_id,
                alert_type="halt",
                current_cost=current_cost,
                threshold=threshold,
            )

    # === STATISTICS ===

    def get_stats(self) -> dict:
        """Get tracker statistics."""
        summary = self.get_summary()
        return {
            "total_cost": summary.total_cost,
            "total_entries": len(self._entries),
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
            "cost_by_category": summary.cost_by_category,
            "cost_by_model": summary.cost_by_model,
            "cost_by_stream": summary.cost_by_stream,
            "circuit_breaker_state": self._circuit_breaker.state.value,
            "circuit_breaker_trip_count": self._circuit_breaker.trip_count,
            "throttle_active": self._throttle_active,
            "policies_configured": len(self._policies),
        }

    # === CALLBACKS ===

    def on_threshold_reached(self, callback: Callable) -> None:
        """Register callback for threshold reached events."""
        self._on_threshold_reached.append(callback)

    def on_budget_exceeded(self, callback: Callable) -> None:
        """Register callback for budget exceeded events."""
        self._on_budget_exceeded.append(callback)

    # === RESET ===

    def reset(self) -> None:
        """Reset all cost tracking data."""
        self._entries.clear()
        self._circuit_breaker.reset()
        self._throttle_active = False
        self._throttle_delay = 0.0
        logger.info("CostTracker reset")


# === FACTORY FUNCTION ===

def create_cost_tracker(
    event_bus: "EventBus | None" = None,
    agent_budget: float | None = None,
    custom_pricing: dict[str, ModelPricing] | None = None,
) -> CostTracker:
    """
    Create and configure a CostTracker.

    Args:
        event_bus: Optional event bus for alerts
        agent_budget: Optional agent-level budget limit
        custom_pricing: Optional custom model pricing

    Returns:
        Configured CostTracker
    """
    tracker = CostTracker(
        event_bus=event_bus,
        custom_pricing=custom_pricing,
    )

    if agent_budget:
        tracker.set_agent_budget(agent_budget)

    return tracker
