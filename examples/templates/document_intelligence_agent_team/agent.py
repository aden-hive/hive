"""Document Intelligence Agent Team — A2A agent with Queen Bee + Worker Bees.

This is the first Hive template to demonstrate the Queen Bee (Orchestrator)
+ Worker Bee (Executor) A2A coordination pattern using delegate_to_sub_agent.

Architecture:
    intake → coordinator → intake (forever-alive loop)

    Sub-agents (no edge connections, invoked via delegate_to_sub_agent):
    - researcher: Entity/fact extraction
    - analyst: Consistency/contradiction detection
    - strategist: Risk/impact assessment
"""

import logging
from pathlib import Path
from typing import Any

from framework.orchestrator import (
    Constraint,
    EdgeCondition,
    EdgeSpec,
    Goal,
    SuccessCriterion,
)
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.orchestrator import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.loader.tool_registry import ToolRegistry
from framework.host.agent_host import AgentHost
from framework.host.execution_manager import EntryPointSpec

from .config import default_config, metadata, worker_models
from .nodes import (
    coordinator_node,
    nodes,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

goal = Goal(
    id="document-intelligence-consensus",
    name="Multi-Perspective Document Intelligence",
    description=(
        "Coordinate specialist agents to perform multi-perspective document "
        "analysis with cross-reference synthesis and consensus detection."
    ),
    success_criteria=[
        SuccessCriterion(
            id="multi-source-analysis",
            description="Document analyzed by at least 3 specialist agents",
            metric="specialist_count",
            target="3",
        ),
        SuccessCriterion(
            id="cross-reference",
            description=(
                "Findings cross-referenced across specialists "
                "with consensus/conflict detection"
            ),
            metric="cross_reference_complete",
            target="true",
        ),
        SuccessCriterion(
            id="structured-report",
            description=(
                "Structured synthesis report generated "
                "and presented to user"
            ),
            metric="report_generated",
            target="true",
        ),
        SuccessCriterion(
            id="source-attribution",
            description=(
                "Every finding attributed to its "
                "source specialist agent"
            ),
            metric="findings_attributed",
            target="true",
        ),
    ],
    constraints=[
        Constraint(
            id="no-external-knowledge",
            description=(
                "Only analyze content within the provided "
                "document — no external knowledge injection"
            ),
            constraint_type="hard",
            category="scope",
        ),
        Constraint(
            id="source-attribution",
            description=(
                "Every claim in the synthesis must be "
                "attributed to its source Worker Bee"
            ),
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="user-review",
            description=(
                "Final report must be presented to "
                "the user for review"
            ),
            constraint_type="hard",
            category="quality",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Edges (only 2 — sub-agents have NO edge connections)
# ---------------------------------------------------------------------------

edges = [
    EdgeSpec(
        id="intake-to-coordinator",
        source="intake",
        target="coordinator",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="coordinator-to-intake",
        source="coordinator",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration — forever-alive pattern
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class DocumentIntelligenceAgentTeam:
    """Document Intelligence Agent Team — A2A Queen Bee + Worker Bees.

    The first Hive template demonstrating the delegate_to_sub_agent
    pattern for multi-agent coordination within a single graph.
    """

    def __init__(
        self,
        config=None,
    ) -> None:
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._graph: GraphSpec | None = None
        self._agent_runtime: AgentHost | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def _apply_worker_models(self) -> list:
        """Apply per-worker model overrides from worker_models config."""
        applied_nodes = []
        model_map = {
            "coordinator": worker_models.coordinator,
            "researcher": worker_models.researcher,
            "analyst": worker_models.analyst,
            "strategist": worker_models.strategist,
        }
        for node in nodes:
            if node.id in model_map and model_map[node.id] is not None:
                # Create a copy with the model override
                node_dict = node.model_dump()
                node_dict["model"] = model_map[node.id]
                applied_nodes.append(type(node)(**node_dict))
            else:
                applied_nodes.append(node)
        return applied_nodes

    def _build_graph(self) -> GraphSpec:
        """Build the agent graph specification."""
        applied_nodes = self._apply_worker_models()
        return GraphSpec(
            id="document-intelligence-team",
            goal_id=goal.id,
            version=metadata.version,
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=applied_nodes,
            edges=edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 100,
                "max_tool_calls_per_turn": 30,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        self._storage_path = (
            Path.home() / ".hive" / "agents" / "document_intelligence_agent_team"
        )
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

        entry_point_specs = [
            EntryPointSpec(
                id="start",
                name="Start Analysis",
                entry_node=self.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            )
        ]

        self._agent_runtime = AgentHost(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
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

    def info(self) -> dict[str, Any]:
        """Return agent information as a dict."""
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {
                "name": goal.name,
                "description": goal.description,
            },
            "nodes": [n.id for n in self.nodes],
            "edges": [e.id for e in self.edges],
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
            "entry_node": self.entry_node,
            "entry_points": self.entry_points,
            "terminal_nodes": self.terminal_nodes,
            "sub_agents": getattr(coordinator_node, "sub_agents", []),
            "pattern": "Queen Bee + Worker Bees (A2A via delegate_to_sub_agent)",
        }

    def validate(self) -> dict[str, Any]:
        """Validate the agent graph structure."""
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
                    f"Entry point '{ep_id}' references "
                    f"unknown node '{node_id}'"
                )

        # Verify sub-agent nodes exist
        for node in self.nodes:
            for sub_agent_id in getattr(node, "sub_agents", []):
                if sub_agent_id not in node_ids:
                    errors.append(
                        f"Node '{node.id}' references "
                        f"unknown sub_agent '{sub_agent_id}'"
                    )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    async def trigger_and_wait(
        self,
        entry_point: str = "start",
        input_data: dict[str, Any] | None = None,
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
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
        self, context: dict[str, Any], mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()


# ---------------------------------------------------------------------------
# Default instance
# ---------------------------------------------------------------------------

default_agent = DocumentIntelligenceAgentTeam()
