# Multi-Entry-Point Agent Architecture

## Executive Summary

This document explains the architectural improvements made to support agents with multiple asynchronous entry points, and why the initial patterns (single-entry execution, tools-as-shared-memory) were insufficient for production use cases.

---

## The Problem: Real-World Agents Need Multiple Entry Points

Consider a Tier-1 support agent that must:

1. **Listen for Zendesk webhooks** - New tickets arrive asynchronously
2. **Handle API requests** - Users can query ticket status or submit follow-ups
3. **Process timer events** - Escalation checks run every 5 minutes
4. **Respond to internal events** - Other agents may delegate work

These are not sequential operations—they happen **concurrently and independently**. A webhook might fire while an API request is being processed. Two tickets might arrive simultaneously.

### Previous Architecture Limitations

The original framework had a fundamental constraint:

```python
# In Runtime (core.py:58)
class Runtime:
    def __init__(self, ...):
        self._current_run: Run | None = None  # Only ONE run at a time
```

This single `_current_run` meant:

- **No concurrent executions** - Processing one ticket blocked all others
- **No multiple entry points** - Only `entry_node` could start execution
- **State collision** - Concurrent attempts would overwrite each other's context

---

## Why Tools-as-Shared-Memory is an Anti-Pattern

A tempting workaround is using tools to manage shared state:

```python
# Anti-pattern: Using tools for state management
@tool
def get_customer_context(customer_id: str) -> dict:
    """Retrieve customer context from database."""
    return db.get_customer(customer_id)

@tool
def update_ticket_status(ticket_id: str, status: str) -> bool:
    """Update ticket status in database."""
    db.update_ticket(ticket_id, status)
    return True
```

This seems to work—tools can read/write external storage, enabling "shared state" between executions. **But this approach has serious problems:**

### 1. Race Conditions Without Isolation Control

```
Execution A: get_customer_context("cust_123") → {tickets: 5}
Execution B: get_customer_context("cust_123") → {tickets: 5}
Execution A: update_ticket_count("cust_123", 6)
Execution B: update_ticket_count("cust_123", 6)  # Should be 7!
```

Tools have no concept of isolation levels. Every call goes directly to storage with no coordination. In high-concurrency scenarios, you get:

- **Lost updates** - Changes overwrite each other
- **Dirty reads** - Reading partially-written state
- **Phantom data** - State changes between reads in the same logical operation

### 2. No Transactional Boundaries

Tools execute independently with no transaction semantics:

```python
# What if this fails halfway?
@tool
def process_refund(order_id: str) -> dict:
    mark_order_refunded(order_id)      # ✓ Succeeds
    credit_customer_account(order_id)   # ✗ Fails - network error
    send_confirmation_email(order_id)   # Never runs
    # Now order is marked refunded but customer wasn't credited!
```

With tools-as-state, there's no way to:

- Roll back partial changes
- Ensure atomic operations
- Coordinate multi-step state transitions

### 3. Invisible Dependencies Break Goal Evaluation

The goal-driven approach relies on tracking decisions and their outcomes:

```python
# Decision: "Update customer tier based on purchase history"
# Outcome: Success/Failure with observable state changes
```

When state flows through tools, the framework loses visibility:

```python
@tool
def update_customer_tier(customer_id: str) -> str:
    # What state did this read? What did it change?
    # The framework has no idea—it just sees "tool returned 'gold'"
    history = get_purchase_history(customer_id)  # Hidden read
    new_tier = calculate_tier(history)           # Hidden logic
    save_tier(customer_id, new_tier)             # Hidden write
    return new_tier
```

This breaks:

- **Outcome aggregation** - Can't track what state changed across executions
- **Constraint checking** - Can't verify invariants were maintained
- **Goal progress evaluation** - Can't correlate actions to success criteria

### 4. No Execution Correlation

When multiple entry points trigger concurrently, you need to:

- Track which execution modified which state
- Correlate related operations (e.g., webhook + follow-up API call for same ticket)
- Debug issues by tracing execution flow

Tools provide none of this. Every tool call is independent with no execution context.

### 5. Testing Becomes Impossible

With tools-as-state:

- **Unit tests** can't isolate state—every test affects global storage
- **Concurrent tests** interfere with each other
- **Mocking** requires replacing actual database/API calls

Compare to proper state management:

```python
# Isolated test - no external dependencies
memory = manager.create_memory("test-exec", "test-stream", IsolationLevel.ISOLATED)
await memory.write("key", "value")
assert await memory.read("key") == "value"
# Other tests unaffected
```

---

## The Solution: Explicit State Management Architecture

The new architecture introduces explicit state management with proper isolation:

```
┌─────────────────────────────────────────────────────┐
│                  AgentRuntime                       │
│  - Manages agent lifecycle                          │
│  - Coordinates ExecutionStreams                     │
│  - Aggregates outcomes for goal evaluation          │
├─────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  Stream A   │  │  Stream B   │  │  Stream C   │ │
│  │ (webhook)   │  │   (api)     │  │  (timer)    │ │
│  │             │  │             │  │             │ │
│  │ Concurrent  │  │ Concurrent  │  │ Concurrent  │ │
│  │ Executions  │  │ Executions  │  │ Executions  │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘ │
│         └────────────────┼────────────────┘        │
│                          ↓                         │
│              SharedStateManager                    │
│              (Isolation Levels)                    │
│                                                    │
│              OutcomeAggregator                     │
│              (Cross-Stream Goals)                  │
└─────────────────────────────────────────────────────┘
```

### Key Components

#### 1. SharedStateManager with Isolation Levels

```python
class IsolationLevel(Enum):
    ISOLATED = "isolated"      # Private state per execution
    SHARED = "shared"          # Visible across executions (eventual consistency)
    SYNCHRONIZED = "synchronized"  # Shared with write locks (strong consistency)
```

Each execution gets explicit control over state visibility:

```python
# Execution-local state (safe from interference)
await memory.write("scratch_data", value, scope=StateScope.EXECUTION)

# Stream-shared state (visible to all executions in this stream)
await memory.write("stream_counter", count, scope=StateScope.STREAM)

# Global state (visible everywhere, use carefully)
await memory.write("system_config", config, scope=StateScope.GLOBAL)
```

#### 2. StreamRuntime with Execution Tracking

```python
class StreamRuntime:
    def __init__(self, stream_id, storage, outcome_aggregator):
        # Track runs by execution_id, not single _current_run
        self._runs: dict[str, Run] = {}
```

Now multiple executions can run concurrently without collision:

```python
# Execution A
runtime.start_run(execution_id="exec-A", goal_id="support")
runtime.decide(execution_id="exec-A", intent="classify ticket", ...)

# Execution B (concurrent, no collision)
runtime.start_run(execution_id="exec-B", goal_id="support")
runtime.decide(execution_id="exec-B", intent="classify ticket", ...)
```

#### 3. OutcomeAggregator for Cross-Stream Goals

```python
class OutcomeAggregator:
    def record_decision(self, stream_id, execution_id, decision) -> None
    def record_outcome(self, stream_id, execution_id, decision_id, outcome) -> None
    async def evaluate_goal_progress(self) -> dict
```

The framework now tracks all decisions across all streams, enabling:

- Unified goal progress evaluation
- Constraint violation detection across executions
- Success criteria tracking with proper attribution

#### 4. EventBus for Coordination

```python
# Stream A publishes
await bus.publish(AgentEvent(
    type=EventType.EXECUTION_COMPLETED,
    stream_id="webhook",
    execution_id="exec-123",
    data={"ticket_resolved": True},
))

# Stream B subscribes
bus.subscribe(
    event_types=[EventType.EXECUTION_COMPLETED],
    handler=on_ticket_resolved,
    filter_stream="webhook",
)
```

Streams can coordinate without tight coupling or shared mutable state.

---

## When Tools ARE Appropriate

Tools remain the right choice for:

1. **External system integration** - Calling APIs, databases, services
2. **Side effects** - Sending emails, creating resources
3. **Data retrieval** - Fetching information needed for decisions

The key distinction:

| Use Case                             | Correct Approach                  |
| ------------------------------------ | --------------------------------- |
| Coordinate between executions        | SharedStateManager                |
| Track decision outcomes              | StreamRuntime + OutcomeAggregator |
| Call external API                    | Tool                              |
| Persist business data                | Tool (to external storage)        |
| Share scratch state during execution | StreamMemory                      |
| Publish events to other streams      | EventBus                          |

---

## Migration Guide

### Before (Anti-Pattern)

```python
# tools.py - State hidden in tools
@tool
def get_processing_count() -> int:
    return redis.get("processing_count") or 0

@tool
def increment_processing_count() -> int:
    return redis.incr("processing_count")
```

### After (Proper Architecture)

```python
# In node execution
async def execute(self, context, memory):
    # Read from managed state
    count = await memory.read("processing_count") or 0

    # Update with proper isolation
    await memory.write(
        "processing_count",
        count + 1,
        scope=StateScope.STREAM,  # Explicit scope
    )
```

---

## Summary

| Aspect        | Tools-as-State   | Explicit State Management |
| ------------- | ---------------- | ------------------------- |
| Concurrency   | Race conditions  | Isolation levels          |
| Transactions  | None             | Execution-scoped          |
| Visibility    | Hidden           | Observable                |
| Testing       | Requires mocking | Isolated by design        |
| Goal tracking | Broken           | Full attribution          |
| Debugging     | Opaque           | Traceable                 |

The multi-entry-point architecture doesn't just enable concurrent execution—it provides the foundation for **reliable, observable, goal-driven agents** that can operate safely in production environments.

---

## References

- [core/framework/runtime/agent_runtime.py](../../core/framework/runtime/agent_runtime.py) - AgentRuntime implementation
- [core/framework/runtime/shared_state.py](../../core/framework/runtime/shared_state.py) - SharedStateManager
- [core/framework/runtime/outcome_aggregator.py](../../core/framework/runtime/outcome_aggregator.py) - Cross-stream goal evaluation
- [core/framework/runtime/tests/test_agent_runtime.py](../../core/framework/runtime/tests/test_agent_runtime.py) - Test examples
