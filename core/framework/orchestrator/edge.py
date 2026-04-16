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
- on_success: Traverse only if source succeeds
- on_failure: Traverse only if source fails
- conditional: Traverse based on expression evaluation (SAFE SUBSET ONLY)
- llm_decide: Let LLM decide based on goal and context (goal-aware routing)

The llm_decide condition is particularly powerful for goal-driven agents,
allowing the LLM to evaluate whether proceeding along an edge makes sense
given the current goal, context, and execution state.
"""

import json
import logging
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from framework.orchestrator.safe_eval import safe_eval

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 8192


class EdgeCondition(StrEnum):
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

    async def should_traverse(
        self,
        source_success: bool,
        source_output: dict[str, Any],
        buffer_data: dict[str, Any],
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
            buffer_data: Current data buffer state
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
            return self._evaluate_condition(source_output, buffer_data)

        if self.condition == EdgeCondition.LLM_DECIDE:
            if llm is None or goal is None:
                # Fallback to ON_SUCCESS if LLM not available
                return source_success
            return await self._llm_decide(
                llm=llm,
                goal=goal,
                source_success=source_success,
                source_output=source_output,
                buffer_data=buffer_data,
                source_node_name=source_node_name,
                target_node_name=target_node_name,
            )

        return False

    def _evaluate_condition(
        self,
        output: dict[str, Any],
        buffer_data: dict[str, Any],
    ) -> bool:
        """Evaluate a conditional expression."""

        if not self.condition_expr:
            return True

        # Build evaluation context
        # Include buffer keys directly for easier access in conditions
        context = {
            "output": output,
            "buffer": buffer_data,
            "result": output.get("result"),
            "true": True,  # Allow lowercase true/false in conditions
            "false": False,
            **buffer_data,  # Unpack buffer keys directly into context
        }

        try:
            # Safe evaluation using AST-based whitelist
            result = bool(safe_eval(self.condition_expr, context))
            # Log the evaluation for visibility
            # Extract the variable names used in the expression for debugging
            expr_vars = {
                k: repr(context[k])
                for k in context
                if k not in ("output", "buffer", "result", "true", "false") and k in self.condition_expr
            }
            logger.info(
                "  Edge %s: condition '%s' → %s  (vars: %s)",
                self.id,
                self.condition_expr,
                result,
                expr_vars or "none matched",
            )
            return result
        except Exception as e:
            logger.warning(f"      ⚠ Condition evaluation failed: {self.condition_expr}")
            logger.warning(f"         Error: {e}")
            logger.warning(f"         Available context keys: {list(context.keys())}")
            return False

    async def _llm_decide(
        self,
        llm: Any,
        goal: Any,
        source_success: bool,
        source_output: dict[str, Any],
        buffer_data: dict[str, Any],
        source_node_name: str | None,
        target_node_name: str | None,
    ) -> bool:
        """
        Use LLM to decide if this edge should be traversed.

        The LLM evaluates whether proceeding to the target node
        is the best next step toward achieving the goal.
        """
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

**Context from data buffer**:
{json.dumps({k: str(v)[:100] for k, v in list(buffer_data.items())[:5]}, indent=2)}

Evaluate whether proceeding to this next node is the right step toward achieving the goal.
Consider:
1. Does the current output suggest we should proceed?
2. Is this the logical next step given the goal?
3. Are there any issues that would make proceeding unwise?

Respond with ONLY a JSON object:
{{"proceed": true/false, "reasoning": "brief explanation"}}"""

        try:
            response = await llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a routing agent. Respond with JSON only.",
                max_tokens=150,
            )

            # Parse response
            json_match = re.search(r"\{[^{}]*\}", response.content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                proceed = data.get("proceed", False)
                reasoning = data.get("reasoning", "")

                # Log the decision (using basic print for now)
                logger.info(f"      🤔 LLM routing decision: {'PROCEED' if proceed else 'SKIP'}")
                logger.info(f"         Reason: {reasoning}")

                return proceed

        except Exception as e:
            # Fallback: proceed on success
            logger.warning(f"      ⚠ LLM routing failed, defaulting to on_success: {e}")
            return source_success

        return source_success

    def map_inputs(
        self,
        source_output: dict[str, Any],
        buffer_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Map source outputs to target inputs.

        Args:
            source_output: Output from source node
            buffer_data: Current data buffer

        Returns:
            Input dict for target node
        """
        if not self.input_mapping:
            # Default: pass through all outputs
            return dict(source_output)

        result = {}
        for target_key, source_key in self.input_mapping.items():
            # Try source output first, then buffer
            if source_key in source_output:
                result[target_key] = source_output[source_key]
            elif source_key in buffer_data:
                result[target_key] = buffer_data[source_key]

        return result


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

    Triggers (timer, webhook, event) are now defined in ``triggers.json``
    alongside the agent directory, not embedded in the graph spec.
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
    terminal_nodes: list[str] = Field(default_factory=list, description="IDs of nodes that end execution")
    pause_nodes: list[str] = Field(default_factory=list, description="IDs of nodes that pause execution for HITL input")

    # Components
    nodes: list[Any] = Field(  # NodeSpec, but avoiding circular import
        default_factory=list, description="All node specifications"
    )
    edges: list[EdgeSpec] = Field(default_factory=list, description="All edge specifications")

    # Data buffer keys
    buffer_keys: list[str] = Field(default_factory=list, description="Keys available in data buffer")

    # Default LLM settings
    default_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = Field(default=None)  # resolved by _resolve_max_tokens validator

    # Cleanup LLM for JSON extraction fallback (fast/cheap model preferred)
    # If not set, uses CEREBRAS_API_KEY -> cerebras/llama-3.3-70b
    cleanup_llm_model: str | None = None

    # Execution limits
    max_steps: int = Field(default=100, description="Maximum node executions before timeout")
    max_retries_per_node: int = 3

    # EventLoopNode configuration (from configure_loop)
    loop_config: dict[str, Any] = Field(
        default_factory=dict,
        description="EventLoopNode configuration (max_iterations, max_tool_calls_per_turn, etc.)",
    )

    # Conversation mode
    conversation_mode: str = Field(
        default="continuous",
        description=(
            "How conversations flow between event_loop nodes. "
            "'continuous' (default): one conversation threads through all "
            "event_loop nodes with cumulative tools and layered prompt composition. "
            "'isolated': each node gets a fresh conversation."
        ),
    )
    identity_prompt: str | None = Field(
        default=None,
        description=(
            "Agent-level identity prompt (Layer 1 of the onion model). "
            "In continuous mode, this is the static identity that persists "
            "unchanged across all node transitions. In isolated mode, ignored."
        ),
    )

    # Metadata
    description: str = ""
    created_by: str = ""  # "human" or "builder_agent"

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _resolve_max_tokens(cls, values: Any) -> Any:
        """Resolve max_tokens from the global config store when not explicitly set."""
        if isinstance(values, dict) and values.get("max_tokens") is None:
            from framework.config import get_max_tokens

            values["max_tokens"] = get_max_tokens()
        return values

    def get_node(self, node_id: str) -> Any | None:
        """Get a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
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

    def validate(self) -> dict[str, list[str]]:
        """Validate the graph structure.

        Returns:
            Dict with 'errors' (blocking issues) and 'warnings' (non-blocking).
        """
        errors = []
        warnings = []

        # Check entry node exists
        if not self.get_node(self.entry_node):
            errors.append(f"Entry node '{self.entry_node}' not found")

        # Check terminal nodes exist
        for term in self.terminal_nodes:
            if not self.get_node(term):
                errors.append(f"Terminal node '{term}' not found")

        # Suggest at least one terminal node (graphs should have termination points)
        if not self.terminal_nodes:
            warnings.append(
                "Graph has no terminal nodes defined in 'terminal_nodes'. "
                "Consider adding a termination point where execution ends."
            )

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

        # Traverse from all entry points
        while to_visit:
            current = to_visit.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in self.get_outgoing_edges(current):
                to_visit.append(edge.target)

        for node in self.nodes:
            if node.id not in reachable:
                # Skip if node is a pause node or entry point target
                if node.id in self.pause_nodes or node.id in self.entry_points.values():
                    continue
                errors.append(f"Node '{node.id}' is unreachable from entry")

        for node in self.nodes:
            if getattr(node, "client_facing", False) and getattr(node, "id", "") != "queen":
                warnings.append(
                    f"Node '{node.id}' sets deprecated client_facing=True. "
                    "Only the queen talks directly to users now; migrate this node "
                    "to queen-mediated escalation."
                )

        # Output key overlap on parallel event_loop nodes
        fan_outs = self.detect_fan_out_nodes()
        for source_id, targets in fan_outs.items():
            event_loop_targets = [
                t for t in targets if self.get_node(t) and getattr(self.get_node(t), "node_type", "") == "event_loop"
            ]
            if len(event_loop_targets) > 1:
                seen_keys: dict[str, str] = {}
                for node_id in event_loop_targets:
                    node = self.get_node(node_id)
                    for key in getattr(node, "output_keys", []):
                        if key in seen_keys:
                            errors.append(
                                f"Fan-out from '{source_id}': event_loop nodes "
                                f"'{seen_keys[key]}' and '{node_id}' both write to "
                                f"output_key '{key}'. Parallel event_loop nodes must "
                                f"have disjoint output_keys to prevent last-wins data loss."
                            )
                        else:
                            seen_keys[key] = node_id

        return {"errors": errors, "warnings": warnings}
