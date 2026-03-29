"""
Orchestration Memory - Cross-agent memory sharing for multi-agent workflows.

Enables agents to share context and knowledge during coordinated workflows.
Builds on top of SharedStateManager with workflow-scoped isolation.

Example:
    # Agent A writes to shared orchestration memory
    await orchestration_memory.share(
        key="search_results",
        value=results,
        from_agent="search_agent",
    )

    # Agent B reads what Agent A shared
    data = await orchestration_memory.read_shared(
        key="search_results",
        from_agent="search_agent",
    )

    # Supervisor gets unified view
    state = orchestration_memory.get_workflow_state()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from framework.runtime.shared_state import SharedStateManager

logger = logging.getLogger(__name__)


class OrchestrationScope(str, Enum):
    """Scope for orchestration memory operations."""

    WORKFLOW = "workflow"  # Shared within a single workflow run
    AGENT_GROUP = "agent_group"  # Shared between a named group of agents
    GLOBAL = "global"  # Shared across all workflows (persistent)


@dataclass
class SharedData:
    """Record of shared data from an agent."""

    key: str
    value: Any
    from_agent: str
    scope: OrchestrationScope
    workflow_id: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContribution:
    """Tracks what an agent has contributed to the workflow."""

    agent_id: str
    keys_written: list[str] = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)


class OrchestrationMemory:
    """
    Memory layer for multi-agent orchestration.

    Provides workflow-scoped memory sharing between agents with:
    - Namespaced keys to prevent collisions
    - Agent attribution for all data
    - Aggregation of parallel agent outputs
    - Subscription to data changes

    State hierarchy:
    - Workflow state: Shared within a single workflow execution
    - Agent group state: Shared between named groups of agents
    - Global state: Shared across all workflows (use sparingly)
    """

    def __init__(
        self,
        workflow_id: str,
        state_manager: "SharedStateManager | None" = None,
    ):
        """
        Initialize orchestration memory.

        Args:
            workflow_id: Unique identifier for this workflow execution
            state_manager: Optional SharedStateManager for backing storage
        """
        self._workflow_id = workflow_id
        self._state_manager = state_manager

        # In-memory storage for workflow-scoped data
        self._workflow_state: dict[str, SharedData] = {}
        self._agent_contributions: dict[str, AgentContribution] = {}
        self._agent_groups: dict[str, set[str]] = {}  # group_name -> {agent_ids}

        # Subscriptions for reactive patterns
        self._subscriptions: dict[str, list[Callable]] = {}  # key -> [handlers]

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

        # History for debugging
        self._history: list[SharedData] = []
        self._max_history = 500

    @property
    def workflow_id(self) -> str:
        """Get the workflow ID."""
        return self._workflow_id

    # === CORE OPERATIONS ===

    async def share(
        self,
        key: str,
        value: Any,
        from_agent: str,
        scope: OrchestrationScope = OrchestrationScope.WORKFLOW,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Share data from one agent to the orchestration memory.

        Args:
            key: Data key (namespaced by agent)
            value: Data to share
            from_agent: Agent ID sharing this data
            scope: Visibility scope (workflow, agent_group, or global)
            metadata: Optional metadata about the data
        """
        async with self._lock:
            # Create namespaced key
            namespaced_key = self._make_key(from_agent, key)

            # Create shared data record
            shared_data = SharedData(
                key=key,
                value=value,
                from_agent=from_agent,
                scope=scope,
                workflow_id=self._workflow_id,
                metadata=metadata or {},
            )

            # Store in workflow state
            self._workflow_state[namespaced_key] = shared_data

            # Track agent contribution
            if from_agent not in self._agent_contributions:
                self._agent_contributions[from_agent] = AgentContribution(
                    agent_id=from_agent
                )
            contribution = self._agent_contributions[from_agent]
            if key not in contribution.keys_written:
                contribution.keys_written.append(key)
            contribution.data[key] = value
            contribution.last_activity = time.time()

            # Add to history
            self._history.append(shared_data)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]

            logger.debug(
                f"Agent '{from_agent}' shared '{key}' in workflow '{self._workflow_id}'"
            )

        # Notify subscribers (outside lock to prevent deadlocks)
        await self._notify_subscribers(key, shared_data)

    async def read_shared(
        self,
        key: str,
        from_agent: str | None = None,
        default: Any = None,
    ) -> Any:
        """
        Read shared data from orchestration memory.

        Args:
            key: Data key to read
            from_agent: Optional - specific agent to read from.
                        If None, returns first match.
            default: Default value if key not found

        Returns:
            The shared value, or default if not found
        """
        async with self._lock:
            if from_agent:
                # Read from specific agent
                namespaced_key = self._make_key(from_agent, key)
                shared_data = self._workflow_state.get(namespaced_key)
                if shared_data:
                    return shared_data.value
            else:
                # Find first agent that has this key
                for namespaced_key, shared_data in self._workflow_state.items():
                    if shared_data.key == key:
                        return shared_data.value

            return default

    async def read_all_from_agent(self, agent_id: str) -> dict[str, Any]:
        """
        Read all data shared by a specific agent.

        Args:
            agent_id: Agent to read from

        Returns:
            Dictionary of key -> value for all data from this agent
        """
        async with self._lock:
            contribution = self._agent_contributions.get(agent_id)
            if contribution:
                return dict(contribution.data)
            return {}

    def read_shared_sync(
        self,
        key: str,
        from_agent: str | None = None,
        default: Any = None,
    ) -> Any:
        """
        Synchronous read for backward compatibility.

        Args:
            key: Data key to read
            from_agent: Optional - specific agent to read from
            default: Default value if key not found

        Returns:
            The shared value, or default if not found
        """
        if from_agent:
            namespaced_key = self._make_key(from_agent, key)
            shared_data = self._workflow_state.get(namespaced_key)
            if shared_data:
                return shared_data.value
        else:
            for shared_data in self._workflow_state.values():
                if shared_data.key == key:
                    return shared_data.value
        return default

    # === AGGREGATION ===

    def get_workflow_state(self) -> dict[str, dict[str, Any]]:
        """
        Get unified view of all agents' contributions.

        Returns:
            Dictionary mapping agent_id -> {key: value, ...}

        Example:
            {
                "search_agent": {"results": [...], "count": 10},
                "reader_agent": {"summary": "...", "pages": 5},
            }
        """
        result = {}
        for agent_id, contribution in self._agent_contributions.items():
            result[agent_id] = dict(contribution.data)
        return result

    async def aggregate(
        self,
        key: str,
        strategy: str = "list",
    ) -> Any:
        """
        Aggregate values for a key from all agents.

        Args:
            key: Key to aggregate
            strategy: Aggregation strategy:
                - "list": Return list of all values
                - "dict": Return dict of agent_id -> value
                - "first": Return first non-None value
                - "last": Return most recent value

        Returns:
            Aggregated result based on strategy
        """
        async with self._lock:
            values = []
            agent_values = {}
            latest_time = 0
            latest_value = None

            for namespaced_key, shared_data in self._workflow_state.items():
                if shared_data.key == key:
                    values.append(shared_data.value)
                    agent_values[shared_data.from_agent] = shared_data.value
                    if shared_data.timestamp > latest_time:
                        latest_time = shared_data.timestamp
                        latest_value = shared_data.value

            if strategy == "list":
                return values
            elif strategy == "dict":
                return agent_values
            elif strategy == "first":
                return values[0] if values else None
            elif strategy == "last":
                return latest_value
            else:
                raise ValueError(f"Unknown aggregation strategy: {strategy}")

    # === AGENT GROUPS ===

    def add_to_group(self, group_name: str, agent_id: str) -> None:
        """
        Add an agent to a named group.

        Args:
            group_name: Name of the group
            agent_id: Agent to add
        """
        if group_name not in self._agent_groups:
            self._agent_groups[group_name] = set()
        self._agent_groups[group_name].add(agent_id)

    def get_group_state(self, group_name: str) -> dict[str, dict[str, Any]]:
        """
        Get state for all agents in a group.

        Args:
            group_name: Name of the group

        Returns:
            Dictionary mapping agent_id -> {key: value, ...} for group members
        """
        if group_name not in self._agent_groups:
            return {}

        result = {}
        for agent_id in self._agent_groups[group_name]:
            if agent_id in self._agent_contributions:
                result[agent_id] = dict(self._agent_contributions[agent_id].data)
        return result

    # === SUBSCRIPTIONS ===

    def subscribe(self, key: str, handler: Callable[[SharedData], Any]) -> str:
        """
        Subscribe to changes for a specific key.

        Args:
            key: Key to watch
            handler: Function to call when key is updated

        Returns:
            Subscription ID
        """
        if key not in self._subscriptions:
            self._subscriptions[key] = []

        sub_id = f"sub_{key}_{len(self._subscriptions[key])}"
        self._subscriptions[key].append(handler)
        return sub_id

    async def _notify_subscribers(self, key: str, data: SharedData) -> None:
        """Notify all subscribers for a key."""
        handlers = self._subscriptions.get(key, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"Error in subscription handler for '{key}': {e}")

    # === UTILITY ===

    def _make_key(self, agent_id: str, key: str) -> str:
        """Create namespaced key."""
        return f"{self._workflow_id}:{agent_id}:{key}"

    def get_contributing_agents(self) -> list[str]:
        """Get list of all agents that have contributed data."""
        return list(self._agent_contributions.keys())

    def get_history(self, limit: int = 50) -> list[SharedData]:
        """Get recent data sharing history."""
        return self._history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get orchestration memory statistics."""
        return {
            "workflow_id": self._workflow_id,
            "total_keys": len(self._workflow_state),
            "contributing_agents": len(self._agent_contributions),
            "agent_groups": len(self._agent_groups),
            "total_subscriptions": sum(
                len(handlers) for handlers in self._subscriptions.values()
            ),
            "history_size": len(self._history),
        }

    async def cleanup(self) -> None:
        """
        Clean up orchestration memory for a completed workflow.

        Call this when the workflow is complete to free resources.
        """
        async with self._lock:
            self._workflow_state.clear()
            self._agent_contributions.clear()
            self._agent_groups.clear()
            self._subscriptions.clear()
            self._history.clear()
            logger.debug(f"Cleaned up orchestration memory for workflow '{self._workflow_id}'")
