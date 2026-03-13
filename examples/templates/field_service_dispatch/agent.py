"""Agent graph construction for Field Service Dispatch Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    intake_node,
    triage_node,
    dispatch_node,
    notify_node,
)

# Goal definition
goal = Goal(
    id="efficient-field-dispatch",
    name="Efficient Field Service Dispatch",
    description=(
        "Handle end-to-end field service dispatch: collect service requests, "
        "triage by priority, match the best technician based on skills and "
        "proximity, and coordinate dispatch with dispatcher approval."
    ),
    success_criteria=[
        SuccessCriterion(
            id="request-completeness",
            description="Service request captured with all required details",
            metric="request_captured",
            target="complete",
            weight=0.3,
        ),
        SuccessCriterion(
            id="triage-accuracy",
            description="Correct priority classification and skill matching",
            metric="triage_accuracy",
            target="correct",
            weight=0.3,
        ),
        SuccessCriterion(
            id="dispatch-quality",
            description="Best technician matched with feasible schedule within SLA",
            metric="dispatch_quality",
            target="within_sla",
            weight=0.25,
        ),
        SuccessCriterion(
            id="notification-sent",
            description="Customer and technician informed of dispatch details",
            metric="notification_sent",
            target="true",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="sla-compliance",
            description="Dispatch must be planned within the SLA window for the priority level",
            constraint_type="functional",
            category="timeliness",
        ),
        Constraint(
            id="skill-match",
            description="Assigned technician must have all required skills/certifications",
            constraint_type="quality",
            category="safety",
        ),
        Constraint(
            id="dispatcher-approval",
            description="Dispatch plan must be approved by dispatcher before execution",
            constraint_type="functional",
            category="interaction",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    triage_node,
    dispatch_node,
    notify_node,
]

# Edge definitions
edges = [
    # intake -> triage_and_plan (always after intake completes)
    EdgeSpec(
        id="intake-to-triage",
        source="intake",
        target="triage_and_plan",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # triage_and_plan -> dispatch (triage complete)
    EdgeSpec(
        id="triage-to-dispatch",
        source="triage_and_plan",
        target="dispatch",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # dispatch -> notify (dispatch plan ready)
    EdgeSpec(
        id="dispatch-to-notify",
        source="dispatch",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # dispatch -> triage_and_plan (reassignment needed — no suitable tech found)
    EdgeSpec(
        id="dispatch-to-triage-reassign",
        source="dispatch",
        target="triage_and_plan",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="'needs_reassignment: true' in str(dispatch_plan).lower()",
        priority=2,
    ),
    # notify -> intake (new dispatch cycle after completion)
    EdgeSpec(
        id="notify-to-intake",
        source="notify",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []


class FieldServiceDispatchAgent:
    """
    Field Service Dispatch Agent — 4-node pipeline with dispatcher approval.

    Flow: intake -> triage_and_plan -> dispatch -> notify
                        ^                  |
                        +-- reassign loop --+ (if no suitable tech)

    Uses AgentRuntime for proper session management:
    - Session-scoped storage (sessions/{session_id}/)
    - Checkpointing for resume capability
    - Runtime logging
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._graph: GraphSpec | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="field-service-dispatch-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 50,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        self._storage_path = Path.home() / ".hive" / "agents" / "field_service_dispatch"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        llm = None
        if not mock_mode:
            llm = LiteLLMProvider(
                model=self.config.model,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
            )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()

        checkpoint_config = CheckpointConfig(
            enabled=True,
            checkpoint_on_node_start=False,
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=7,
            async_checkpoint=True,
        )

        entry_point_specs = [
            EntryPointSpec(
                id="default",
                name="Default",
                entry_node=self.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            )
        ]

        self._agent_runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
        )

    async def start(self, mock_mode=False) -> None:
        """Set up and start the agent runtime."""
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime and clean up."""
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def trigger_and_wait(
        self,
        entry_point: str = "default",
        input_data: dict | None = None,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")

        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data or {},
            session_state=session_state,
        )

    async def run(
        self, context: dict, mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
        """Get agent information."""
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {
                "name": self.goal.name,
                "description": self.goal.description,
            },
            "nodes": [n.id for n in self.nodes],
            "edges": [e.id for e in self.edges],
            "entry_node": self.entry_node,
            "entry_points": self.entry_points,
            "pause_nodes": self.pause_nodes,
            "terminal_nodes": self.terminal_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self):
        """Validate agent structure."""
        errors = []
        warnings = []

        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")

        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")

        for terminal in self.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node '{terminal}' not found")

        for ep_id, node_id in self.entry_points.items():
            if node_id not in node_ids:
                errors.append(
                    f"Entry point '{ep_id}' references unknown node '{node_id}'"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = FieldServiceDispatchAgent()
