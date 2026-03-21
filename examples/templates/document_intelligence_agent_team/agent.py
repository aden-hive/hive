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

from framework.graph import Constraint, Goal, SuccessCriterion
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig
from framework.runtime.execution_stream import EntryPointSpec

from .config import AgentMetadata, RuntimeConfig, default_config, metadata, worker_models
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
    ):
        self.config = config or default_config
        self.metadata = agent_metadata or metadata
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
        kwargs = {
            "id": "document-intelligence-team",
            "goal_id": goal.id,
            "version": self.metadata.version,
            "entry_node": "intake",
            "entry_points": {"start": "intake"},
            "terminal_nodes": [],  # forever-alive
            "pause_nodes": [],
            "nodes": applied_nodes,
            "edges": edges,
        }
        if self.config.model is not None:
            kwargs["default_model"] = self.config.model
        return GraphSpec(**kwargs)

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
            config=AgentRuntimeConfig(
                max_concurrent_executions=self.config.max_concurrent,
            ),
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

    async def start(self):
        """Start the agent runtime."""
        if self._runtime is None:
            self.build_runtime()
        await self._runtime.start()

    async def stop(self):
        """Stop the agent runtime."""
        if self._runtime:
            await self._runtime.stop()

    def info(self) -> str:
        """Return agent information string."""
        return (
            f"Agent: {self.metadata.name} v{self.metadata.version}\n"
            f"Description: {self.metadata.description}\n"
            f"Nodes: {len(nodes)}\n"
            f"  - intake (client-facing)\n"
            f"  - coordinator (Queen Bee, sub_agents: researcher, analyst, strategist)\n"
            f"  - researcher (Worker Bee)\n"
            f"  - analyst (Worker Bee)\n"
            f"  - strategist (Worker Bee)\n"
            f"Edges: {len(edges)} (intake↔coordinator loop)\n"
            f"Pattern: Queen Bee + Worker Bees (A2A via delegate_to_sub_agent)\n"
            f"Mode: forever-alive"
        )

    def validate(self) -> dict:
        """Validate the agent graph structure."""
        graph = self.build_graph()
        issues = graph.validate()
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "sub_agents": coordinator_node.sub_agents,
        }


# ---------------------------------------------------------------------------
# Default instance
# ---------------------------------------------------------------------------

default_agent = DocumentIntelligenceAgentTeam()
