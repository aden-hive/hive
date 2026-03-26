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

from framework.config import RuntimeConfig
from framework.graph import Constraint, Goal, SuccessCriterion
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import ExecutionResult
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.execution_stream import EntryPointSpec

from .config import AgentMetadata, default_config, metadata, worker_models
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
        config: RuntimeConfig | None = None,
        agent_metadata: AgentMetadata | None = None,
    ) -> None:
        self.config = config or default_config
        self.metadata = agent_metadata or metadata
        self.goal = goal
        self._runtime: AgentRuntime | None = None

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

    def build_graph(self) -> GraphSpec:
        """Build the agent graph specification."""
        applied_nodes = self._apply_worker_models()
        return GraphSpec(
            id="document-intelligence-team",
            goal_id=goal.id,
            version=self.metadata.version,
            entry_node="intake",
            entry_points={"start": "intake"},
            terminal_nodes=[],  # forever-alive
            pause_nodes=[],
            nodes=applied_nodes,
            edges=edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
        )

    def build_runtime(
        self,
        storage_path: str | Path = "./storage/document_intelligence",
        llm=None,
        tools=None,
        tool_executor=None,
    ) -> AgentRuntime:
        """Build and configure the agent runtime."""
        graph = self.build_graph()
        runtime = AgentRuntime(
            graph=graph,
            goal=goal,
            storage_path=storage_path,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
        )
        runtime.intro_message = self.metadata.intro_message

        # Register the default entry point
        runtime.register_entry_point(
            EntryPointSpec(
                id="start",
                name="Start Analysis",
                entry_node="intake",
                trigger_type="manual",
                isolation_level="shared",
            )
        )

        self._runtime = runtime
        return runtime

    async def start(self) -> None:
        """Start the agent runtime."""
        if self._runtime is None:
            self.build_runtime()
        await self._runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime."""
        if self._runtime:
            await self._runtime.stop()

    def info(self) -> dict[str, Any]:
        """Return agent information as a dict."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "goal": {
                "name": goal.name,
                "description": goal.description,
            },
            "nodes": [n.id for n in nodes],
            "edges": [e.id for e in edges],
            "client_facing_nodes": [n.id for n in nodes if n.client_facing],
            "entry_node": "intake",
            "entry_points": {"start": "intake"},
            "terminal_nodes": [],
            "sub_agents": coordinator_node.sub_agents,
            "pattern": "Queen Bee + Worker Bees (A2A via delegate_to_sub_agent)",
        }

    def validate(self) -> dict[str, Any]:
        """Validate the agent graph structure."""
        graph = self.build_graph()
        issues = graph.validate()
        return {
            "valid": len(issues["errors"]) == 0,
            "errors": issues["errors"],
            "warnings": issues["warnings"],
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "sub_agents": coordinator_node.sub_agents,
        }

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """Delegate trigger_and_wait to the underlying runtime."""
        if self._runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")
        return await self._runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data,
            timeout=timeout,
            session_state=session_state,
        )

    async def run(
        self, context: dict[str, Any], session_state: dict[str, Any] | None = None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start()
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
