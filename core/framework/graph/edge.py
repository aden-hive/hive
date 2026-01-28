"""
Edge Protocol - How nodes connect in a graph.

Edges define:
1. Source and target nodes
2. Conditions for traversal
3. Data mapping between nodes

Unlike traditional graph frameworks where edges are programmatic,
our edges can be created dynamically by a Builder agent based on the goal.

Edge Types:
- always: Always traverse after source completes
- always: Always traverse after source completes
- on_success: Traverse only if source succeeds
- on_failure: Traverse only if source fails
- conditional: Traverse based on expression evaluation (SAFE SUBSET ONLY)
- llm_decide: Let LLM decide based on goal and context (goal-aware routing)

The llm_decide condition is particularly powerful for goal-driven agents,
allowing the LLM to evaluate whether proceeding along an edge makes sense
given the current goal, context, and execution state.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from framework.graph.safe_eval import safe_eval


class EdgeCondition(str, Enum):
    """When an edge should be traversed."""

    ALWAYS = "always"  # Always after source completes
    ON_SUCCESS = "on_success"  # Only if source succeeds
    ON_FAILURE = "on_failure"  # Only if source fails
    CONDITIONAL = "conditional"  # Based on expression
    LLM_DECIDE = "llm_decide"  # Let LLM decide based on goal and context


class EdgeSpec(BaseModel):
    """
    Specification for an edge between nodes.

    Examples:
        # Simple success-based routing
        EdgeSpec(
            id="calc-to-format",
            source="calculator",
            target="formatter",
            condition=EdgeCondition.ON_SUCCESS,
            input_mapping={"result": "value_to_format"}
        )

        # Conditional routing based on output
        EdgeSpec(
            id="validate-to-retry",
            source="validator",
            target="retry_handler",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.confidence < 0.8",
        )

        # LLM-powered routing (goal-aware)
        EdgeSpec(
            id="search-to-filter",
            source="search_results",
            target="filter_results",
            condition=EdgeCondition.LLM_DECIDE,
            description="Only filter if results need refinement to meet goal",
        )
    """

    id: str
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")

    # When to traverse
    condition: EdgeCondition = EdgeCondition.ALWAYS
    condition_expr: str | None = Field(
        default=None,
        description="Expression for CONDITIONAL edges, e.g., 'output.confidence > 0.8'",
    )

    # Data flow
    input_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Map source outputs to target inputs: {target_key: source_key}",
    )

    # Priority for multiple outgoing edges
    priority: int = Field(default=0, description="Higher priority edges are evaluated first")

    # Metadata
    description: str = ""

    model_config = {"extra": "allow"}

    def should_traverse(
        self,
        source_success: bool,
        source_output: dict[str, Any],
        memory: dict[str, Any],
        llm: Any | None = None,
        goal: Any | None = None,
        source_node_name: str | None = None,
        target_node_name: str | None = None,
    ) -> bool:
        """
        Determine if this edge should be traversed.

        Args:
            source_success: Whether the source node succeeded
            source_output: Output from the source node
            memory: Current shared memory state
            llm: LLM provider for LLM_DECIDE edges
            goal: Goal object for LLM_DECIDE edges
            source_node_name: Name of source node (for LLM context)
            target_node_name: Name of target node (for LLM context)

        Returns:
            True if the edge should be traversed
        """
        if self.condition == EdgeCondition.ALWAYS:
            return True

        if self.condition == EdgeCondition.ON_SUCCESS:
            return source_success

        if self.condition == EdgeCondition.ON_FAILURE:
            return not source_success

        if self.condition == EdgeCondition.CONDITIONAL:
            return self._evaluate_condition(source_output, memory)

        if self.condition == EdgeCondition.LLM_DECIDE:
            if llm is None or goal is None:
                # Fallback to ON_SUCCESS if LLM not available
                return source_success
            return self._llm_decide(
                llm=llm,
                goal=goal,
                source_success=source_success,
                source_output=source_output,
                memory=memory,
                source_node_name=source_node_name,
                target_node_name=target_node_name,
            )

        return False

    def _evaluate_condition(
        self,
        output: dict[str, Any],
        memory: dict[str, Any],
    ) -> bool:
        """Evaluate a conditional expression."""
        if not self.condition_expr:
            return True

        # Build evaluation context
        # Include memory keys directly for easier access in conditions
        context = {
            "output": output,
            "memory": memory,
            "result": output.get("result"),
            "true": True,  # Allow lowercase true/false in conditions
            "false": False,
            **memory,  # Unpack memory keys directly into context
        }

        try:
            # Safe evaluation using AST-based whitelist
            return bool(safe_eval(self.condition_expr, context))
        except Exception as e:
            # Log the error for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"      ⚠ Condition evaluation failed: {self.condition_expr}")
            logger.warning(f"         Error: {e}")
            logger.warning(f"         Available context keys: {list(context.keys())}")
            return False

    def _llm_decide(
        self,
        llm: Any,
        goal: Any,
        source_success: bool,
        source_output: dict[str, Any],
        memory: dict[str, Any],
        source_node_name: str | None,
        target_node_name: str | None,
    ) -> bool:
        """
        Use LLM to decide if this edge should be traversed.

        The LLM evaluates whether proceeding to the target node
        is the best next step toward achieving the goal.
        """
        import json

        # Build context for LLM
        prompt = f"""You are evaluating whether to proceed along an edge in an agent workflow.

**Goal**: {goal.name}
{goal.description}

**Current State**:
- Just completed: {source_node_name or "unknown node"}
- Success: {source_success}
- Output: {json.dumps(source_output, default=str)}

**Decision**:
Should we proceed to: {target_node_name or self.target}?
Edge description: {self.description or "No description"}

**Context from memory**:
{json.dumps({k: str(v)[:100] for k, v in list(memory.items())[:5]}, indent=2)}

Evaluate whether proceeding to this next node is the right step toward achieving the goal.
Consider:
1. Does the current output suggest we should proceed?
2. Is this the logical next step given the goal?
3. Are there any issues that would make proceeding unwise?

Respond with ONLY a JSON object:
{{"proceed": true/false, "reasoning": "brief explanation"}}"""

        try:
            response = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a routing agent. Respond with JSON only.",
                max_tokens=150,
            )

            # Parse response
            import re

            json_match = re.search(r"\{[^{}]*\}", response.content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                proceed = data.get("proceed", False)
                reasoning = data.get("reasoning", "")

                # Log the decision (using basic print for now)
                import logging

                logger = logging.getLogger(__name__)
                logger.info(f"      🤔 LLM routing decision: {'PROCEED' if proceed else 'SKIP'}")
                logger.info(f"         Reason: {reasoning}")

                return proceed

        except Exception as e:
            # Fallback: proceed on success
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"      ⚠ LLM routing failed, defaulting to on_success: {e}")
            return source_success

        return source_success

    def map_inputs(
        self,
        source_output: dict[str, Any],
        memory: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Map source outputs to target inputs.

        Args:
            source_output: Output from source node
            memory: Current shared memory

        Returns:
            Input dict for target node
        """
        if not self.input_mapping:
            # Default: pass through all outputs
            return dict(source_output)

        result = {}
        for target_key, source_key in self.input_mapping.items():
            # Try source output first, then memory
            if source_key in source_output:
                result[target_key] = source_output[source_key]
            elif source_key in memory:
                result[target_key] = memory[source_key]

        return result


class AsyncEntryPointSpec(BaseModel):
    """
    Specification for an asynchronous entry point.

    Used with AgentRuntime for multi-entry-point agents that handle
    concurrent execution streams (e.g., webhook + API handlers).

    Example:
        AsyncEntryPointSpec(
            id="webhook",
            name="Zendesk Webhook Handler",
            entry_node="process-webhook",
            trigger_type="webhook",
            isolation_level="shared",
        )
    """

    id: str = Field(description="Unique identifier for this entry point")
    name: str = Field(description="Human-readable name")
    entry_node: str = Field(description="Node ID to start execution from")
    trigger_type: str = Field(
        default="manual",
        description="How this entry point is triggered: webhook, api, timer, event, manual",
    )
    trigger_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Trigger-specific configuration (e.g., webhook URL, timer interval)",
    )
    isolation_level: str = Field(
        default="shared", description="State isolation: isolated, shared, or synchronized"
    )
    priority: int = Field(default=0, description="Execution priority (higher = more priority)")
    max_concurrent: int = Field(
        default=10, description="Maximum concurrent executions for this entry point"
    )

    model_config = {"extra": "allow"}


class GraphSpec(BaseModel):
    """
    Complete specification of an agent graph.

    Contains all nodes, edges, and metadata needed to execute.

    For single-entry-point agents (traditional pattern):
        GraphSpec(
            id="calculator-graph",
            goal_id="calc-001",
            entry_node="input_parser",
            terminal_nodes=["output_formatter", "error_handler"],
            nodes=[...],
            edges=[...],
        )

    For multi-entry-point agents (concurrent streams):
        GraphSpec(
            id="support-agent-graph",
            goal_id="support-001",
            entry_node="process-webhook",  # Default entry
            async_entry_points=[
                AsyncEntryPointSpec(
                    id="webhook",
                    name="Zendesk Webhook",
                    entry_node="process-webhook",
                    trigger_type="webhook",
                ),
                AsyncEntryPointSpec(
                    id="api",
                    name="API Handler",
                    entry_node="process-request",
                    trigger_type="api",
                ),
            ],
            nodes=[...],
            edges=[...],
        )
    """

    id: str
    goal_id: str
    version: str = "1.0.0"

    # Graph structure
    entry_node: str = Field(description="ID of the first node to execute")
    entry_points: dict[str, str] = Field(
        default_factory=dict,
        description="Named entry points for resuming execution. Format: {name: node_id}",
    )
    async_entry_points: list[AsyncEntryPointSpec] = Field(
        default_factory=list,
        description=(
            "Asynchronous entry points for concurrent execution streams (used with AgentRuntime)"
        ),
    )
    terminal_nodes: list[str] = Field(
        default_factory=list, description="IDs of nodes that end execution"
    )
    pause_nodes: list[str] = Field(
        default_factory=list, description="IDs of nodes that pause execution for HITL input"
    )

    # Components
    nodes: list[Any] = Field(  # NodeSpec, but avoiding circular import
        default_factory=list, description="All node specifications"
    )
    edges: list[EdgeSpec] = Field(default_factory=list, description="All edge specifications")

    # Shared memory keys
    memory_keys: list[str] = Field(
        default_factory=list, description="Keys available in shared memory"
    )

    # Default LLM settings
    default_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 1024

    # Cleanup LLM for JSON extraction fallback (fast/cheap model preferred)
    # If not set, uses CEREBRAS_API_KEY -> cerebras/llama-3.3-70b or
    # ANTHROPIC_API_KEY -> claude-3-5-haiku as fallback
    cleanup_llm_model: str | None = None

    # Execution limits
    max_steps: int = Field(default=100, description="Maximum node executions before timeout")
    max_retries_per_node: int = 3

    # Metadata
    description: str = ""
    created_by: str = ""  # "human" or "builder_agent"

    model_config = {"extra": "allow"}

    def get_node(self, node_id: str) -> Any | None:
        """Get a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def has_async_entry_points(self) -> bool:
        """Check if this graph uses async entry points (multi-stream execution)."""
        return len(self.async_entry_points) > 0

    def get_async_entry_point(self, entry_point_id: str) -> AsyncEntryPointSpec | None:
        """Get an async entry point by ID."""
        for ep in self.async_entry_points:
            if ep.id == entry_point_id:
                return ep
        return None

    def get_outgoing_edges(self, node_id: str) -> list[EdgeSpec]:
        """Get all edges leaving a node, sorted by priority."""
        edges = [e for e in self.edges if e.source == node_id]
        return sorted(edges, key=lambda e: -e.priority)

    def get_incoming_edges(self, node_id: str) -> list[EdgeSpec]:
        """Get all edges entering a node."""
        return [e for e in self.edges if e.target == node_id]

    def detect_fan_out_nodes(self) -> dict[str, list[str]]:
        """
        Detect nodes that fan-out to multiple targets.

        A fan-out occurs when a node has multiple outgoing edges with the same
        condition (typically ON_SUCCESS) that should execute in parallel.

        Returns:
            Dict mapping source_node_id -> list of parallel target_node_ids
        """
        fan_outs: dict[str, list[str]] = {}
        for node in self.nodes:
            outgoing = self.get_outgoing_edges(node.id)
            # Fan-out: multiple edges with ON_SUCCESS condition
            success_edges = [e for e in outgoing if e.condition == EdgeCondition.ON_SUCCESS]
            if len(success_edges) > 1:
                fan_outs[node.id] = [e.target for e in success_edges]
        return fan_outs

    def detect_fan_in_nodes(self) -> dict[str, list[str]]:
        """
        Detect nodes that receive from multiple sources (fan-in / convergence).

        A fan-in occurs when a node has multiple incoming edges, meaning
        it should wait for all predecessor branches to complete.

        Returns:
            Dict mapping target_node_id -> list of source_node_ids
        """
        fan_ins: dict[str, list[str]] = {}
        for node in self.nodes:
            incoming = self.get_incoming_edges(node.id)
            if len(incoming) > 1:
                fan_ins[node.id] = [e.source for e in incoming]
        return fan_ins

    def get_entry_point(self, session_state: dict | None = None) -> str:
        """
        Get the appropriate entry point based on session state.

        Args:
            session_state: Optional session state with 'paused_at' or 'resume_from' key

        Returns:
            Node ID to start execution from
        """
        if not session_state:
            return self.entry_node

        # Check if resuming from a pause node
        paused_at = session_state.get("paused_at")
        if paused_at and paused_at in self.pause_nodes:
            # Look for a resume entry point
            resume_key = f"{paused_at}_resume"
            if resume_key in self.entry_points:
                return self.entry_points[resume_key]

        # Check for explicit resume_from
        resume_from = session_state.get("resume_from")
        if resume_from:
            if resume_from in self.entry_points:
                return self.entry_points[resume_from]
            elif resume_from in [n.id for n in self.nodes]:
                return resume_from

        # Default to main entry
        return self.entry_node

    def validate(self) -> list[str]:
        """Validate the graph structure."""
        errors = []

        # Check entry node exists
        if not self.get_node(self.entry_node):
            errors.append(f"Entry node '{self.entry_node}' not found")

        # Check async entry points
        seen_entry_ids = set()
        for entry_point in self.async_entry_points:
            # Check for duplicate IDs
            if entry_point.id in seen_entry_ids:
                errors.append(f"Duplicate async entry point ID: '{entry_point.id}'")
            seen_entry_ids.add(entry_point.id)

            # Check entry node exists
            if not self.get_node(entry_point.entry_node):
                errors.append(
                    f"Async entry point '{entry_point.id}' references "
                    f"missing node '{entry_point.entry_node}'"
                )

            # Validate isolation level
            valid_isolation = {"isolated", "shared", "synchronized"}
            if entry_point.isolation_level not in valid_isolation:
                errors.append(
                    f"Async entry point '{entry_point.id}' has invalid isolation_level "
                    f"'{entry_point.isolation_level}'. Valid: {valid_isolation}"
                )

            # Validate trigger type
            valid_triggers = {"webhook", "api", "timer", "event", "manual"}
            if entry_point.trigger_type not in valid_triggers:
                errors.append(
                    f"Async entry point '{entry_point.id}' has invalid trigger_type "
                    f"'{entry_point.trigger_type}'. Valid: {valid_triggers}"
                )

        # Check terminal nodes exist
        for term in self.terminal_nodes:
            if not self.get_node(term):
                errors.append(f"Terminal node '{term}' not found")

        # Check edge references
        for edge in self.edges:
            if not self.get_node(edge.source):
                errors.append(f"Edge '{edge.id}' references missing source '{edge.source}'")
            if not self.get_node(edge.target):
                errors.append(f"Edge '{edge.id}' references missing target '{edge.target}'")

        # Check for unreachable nodes
        # Start with main entry node and all entry points (for pause/resume architecture)
        reachable = set()
        to_visit = [self.entry_node]

        # Add all entry points as valid starting points (they're reachable by definition)
        for entry_point_node in self.entry_points.values():
            to_visit.append(entry_point_node)

        # Add all async entry points as valid starting points
        for async_entry in self.async_entry_points:
            to_visit.append(async_entry.entry_node)

        # Traverse from all entry points
        while to_visit:
            current = to_visit.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in self.get_outgoing_edges(current):
                to_visit.append(edge.target)

        # Build set of async entry point nodes for quick lookup
        async_entry_nodes = {ep.entry_node for ep in self.async_entry_points}

        for node in self.nodes:
            if node.id not in reachable:
                # Skip if node is a pause node, entry point target, or async entry
                # (pause/resume architecture and async entry points make reachable)
                if (
                    node.id in self.pause_nodes
                    or node.id in self.entry_points.values()
                    or node.id in async_entry_nodes
                ):
                    continue
                errors.append(f"Node '{node.id}' is unreachable from entry")

        return errors
