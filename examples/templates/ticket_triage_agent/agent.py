"""Agent graph construction for Ticket Triage Agent."""

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
    classify_node,
    assign_node,
    draft_node,
    approval_node,
)

# Goal definition
goal = Goal(
    id="support-ticket-triage",
    name="Support Ticket Triage",
    description=(
        "Automatically triage incoming customer support tickets by classifying "
        "priority, assigning to the correct team, drafting a first response, "
        "and pausing for human approval on critical tickets."
    ),
    success_criteria=[
        SuccessCriterion(
            id="priority-classification",
            description="Every ticket is assigned a valid priority level",
            metric="priority_assigned",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="team-assignment",
            description="Every ticket is routed to the correct team",
            metric="team_assigned",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="draft-response",
            description="A professional draft response is created for every ticket",
            metric="draft_created",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="human-approval",
            description="Critical tickets are reviewed by a human before response is sent",
            metric="critical_approved",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="no-assumptions",
            description="Do not assume ticket details not present in the input",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="human-in-the-loop",
            description="Critical tickets must always pause for human approval",
            constraint_type="functional",
            category="safety",
        ),
        Constraint(
            id="professional-tone",
            description="All draft responses must be professional and empathetic",
            constraint_type="quality",
            category="communication",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    classify_node,
    assign_node,
    draft_node,
    approval_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-classify",
        source="intake",
        target="classify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-assign",
        source="classify",
        target="assign",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="assign-to-draft",
        source="assign",
        target="draft",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="draft-to-approval",
        source="draft",
        target="approval",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = ["approval"]
terminal_nodes = ["approval"]


class TicketTriageAgent:
    """
    Ticket Triage Agent — 5 node pipeline.

    Flow: intake -> classify -> assign -> draft -> approval

    - intake: receives the ticket
    - classify: assigns priority
    - assign: routes to correct team
    - draft: writes first response
    - approval: human review for Critical tickets
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
        return GraphSpec(
            id="ticket-triage-agent-graph",
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
                "max_history_tokens": 16000,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        storage_path = Path.home() / ".hive" / "agents" / "ticket_triage_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

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
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
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
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
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
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Default instance
default_agent = TicketTriageAgent()
