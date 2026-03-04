"""Agent graph construction for Issue Triage Agent."""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import fetch_signals_node, intake_node, report_node, triage_and_route_node


goal = Goal(
    id="cross-channel-issue-triage",
    name="Cross-Channel Issue Triage",
    description=(
        "Triage incoming signals from Discord, Gmail, and GitHub issues into a "
        "single prioritized queue with consistent severity, routing, and follow-up actions."
    ),
    success_criteria=[
        SuccessCriterion(
            id="coverage",
            description="Collect candidate reports from all configured channels",
            metric="source_coverage",
            target="100% of configured sources",
            weight=0.25,
        ),
        SuccessCriterion(
            id="classification-quality",
            description="Each unified issue gets category, severity, and rationale",
            metric="classified_issue_ratio",
            target=">=95%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="routing-completion",
            description="High-priority items are routed and acknowledged",
            metric="routed_high_priority_ratio",
            target=">=95%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="operator-visibility",
            description="Operator receives a clear triage report for each run",
            metric="report_delivery",
            target="100%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="no-auto-close",
            description="Never close GitHub issues automatically",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="draft-only-email",
            description="Only draft email responses; never send automatically",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="traceable-triage",
            description="Every severity decision must include a concise rationale",
            constraint_type="quality",
            category="auditability",
        ),
    ],
)

nodes = [
    intake_node,
    fetch_signals_node,
    triage_and_route_node,
    report_node,
]

edges = [
    EdgeSpec(
        id="intake-to-fetch",
        source="intake",
        target="fetch-signals",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="fetch-to-triage",
        source="fetch-signals",
        target="triage-and-route",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="triage-to-report",
        source="triage-and-route",
        target="report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="report-to-fetch",
        source="report",
        target="fetch-signals",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(next_action).lower() == 'run_again'",
        priority=2,
    ),
    EdgeSpec(
        id="report-to-intake",
        source="report",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(next_action).lower() == 'refine_policy'",
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []
loop_config = {
    "max_iterations": 120,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}
conversation_mode = "continuous"
identity_prompt = (
    "You are an operations-grade issue triage assistant. You ingest reports from "
    "Discord, Gmail, and GitHub issues, assign severity consistently, and route work "
    "to the right place while keeping humans in control of final decisions."
)


class IssueTriageAgent:
    """Cross-channel issue triage agent."""

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
            id="issue-triage-agent-graph",
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
            loop_config=loop_config,
            conversation_mode=conversation_mode,
            identity_prompt=identity_prompt,
        )

    def _setup(self, mock_mode=False) -> None:
        self._storage_path = Path.home() / ".hive" / "agents" / "issue_triage_agent"
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
            graph_id="issue_triage_agent",
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
            timeout=timeout,
            session_state=session_state,
        )

    async def run(self, context: dict, mock_mode=False, session_state=None) -> ExecutionResult:
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait("default", context, session_state=session_state)
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
                errors.append(f"Edge {edge.id}: source {edge.source} not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target {edge.target} not found")

        if self.entry_node not in node_ids:
            errors.append(f"Entry node {self.entry_node} not found")

        for terminal in self.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node {terminal} not found")

        for ep_id, node_id in self.entry_points.items():
            if node_id not in node_ids:
                errors.append(
                    f"Entry point {ep_id} references unknown node {node_id}"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = IssueTriageAgent()
