"""Agent graph construction for Viral Tech Copywriter (Option B: interactive intake)."""

from __future__ import annotations

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.core import Runtime
from framework.runtime.event_bus import EventBus

from .config import default_config, metadata
from .nodes import (
    deliver_exports_node,
    intake_node,
    normalize_brief_node,
    write_package_node,
)

# Loads hive-tools MCP (save_data, append_data, serve_file_to_user, etc.).
skip_credential_validation = True

goal = Goal(
    id="viral-tech-copywriter-goal",
    name="Viral Tech Copywriter",
    description=(
        "Capture a marketing brief through conversation, normalize it into structured "
        "JSON, produce hook-heavy platform copy, then export HTML and/or Markdown with "
        "user-chosen formats—without fabricating facts."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-brief-captured",
            description="Intake produces a raw_brief with product, ICP, and platforms",
            metric="brief_completeness",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-structured",
            description="structured_brief matches schema and uses only provided facts",
            metric="brief_schema",
            target="valid",
            weight=0.18,
        ),
        SuccessCriterion(
            id="sc-hooks",
            description="Multiple distinct hook angles, not trivial paraphrases",
            metric="hook_diversity",
            target=">=4",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-channels",
            description="Requested platforms receive tailored copy with CTAs where apt",
            metric="channel_coverage",
            target="100%",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-constraints",
            description="Honors tone, banned phrases, and no fabricated metrics",
            metric="constraint_adherence",
            target="true",
            weight=0.12,
        ),
        SuccessCriterion(
            id="sc-export",
            description=(
                "User-selected HTML/Markdown files created, served, and listed in "
                "delivered_artifacts"
            ),
            metric="export_delivery",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-fabrication",
            description="Do not invent customers, metrics, logos, or press quotes",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-verify",
            description="Flag uncertain claims in verify_flags or notes, not as facts",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-json-outputs",
            description=(
                "normalize-brief and write-package emit parseable JSON; "
                "delivered_artifacts lists served files"
            ),
            constraint_type="hard",
            category="functional",
        ),
    ],
)

nodes = [
    intake_node,
    normalize_brief_node,
    write_package_node,
    deliver_exports_node,
]

edges = [
    EdgeSpec(
        id="intake-to-normalize",
        source="intake",
        target="normalize-brief",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="normalize-to-write",
        source="normalize-brief",
        target="write-package",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="write-to-deliver",
        source="write-package",
        target="deliver-exports",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["deliver-exports"]


class ViralTechCopywriterAgent:
    """Viral Tech Copywriter — intake → normalize-brief → write-package → deliver-exports."""

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._executor: GraphExecutor | None = None
        self._graph: GraphSpec | None = None
        self._event_bus: EventBus | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="viral-tech-copywriter-graph",
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
                "max_iterations": 55,
                "max_tool_calls_per_turn": 36,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self) -> GraphExecutor:
        storage_path = Path.home() / ".hive" / "agents" / "viral_tech_copywriter"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()
        runtime = Runtime(storage_path)

        self._executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            event_bus=self._event_bus,
            storage_path=storage_path,
            loop_config=self._graph.loop_config,
        )

        return self._executor

    async def start(self) -> None:
        if self._executor is None:
            self._setup()

    async def stop(self) -> None:
        self._executor = None
        self._event_bus = None

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        if self._executor is None:
            raise RuntimeError("Agent not started. Call start() first.")
        if self._graph is None:
            raise RuntimeError("Graph not built. Call start() first.")

        return await self._executor.execute(
            graph=self._graph,
            goal=self.goal,
            input_data=input_data,
            session_state=session_state,
        )

    async def run(self, context: dict, session_state=None) -> ExecutionResult:
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
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


default_agent = ViralTechCopywriterAgent()
