"""Agent graph construction for Automated HR Screener."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    intake_node,
    scan_resumes_node,
    rank_candidates_node,
    generate_report_node,
    notify_candidates_node,
)

# Goal definition
goal = Goal(
    id="hr-screening",
    name="Automated HR Screener",
    description=(
        "Screen PDF resumes against a job description, score and rank "
        "candidates 1-100, produce a Top-5 report, and optionally send "
        "personalized response emails — all while keeping applicant "
        "data private on the local machine."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-resumes-scanned",
            description="Successfully reads and extracts text from all PDF resumes in the folder",
            metric="resumes_scanned",
            target=">=1",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-candidates-scored",
            description="Scores every candidate 1-100 with clear reasoning",
            metric="candidates_scored",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-top5-report",
            description="Produces a plain text report of the Top 5 candidates",
            metric="report_generated",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-privacy-compliance",
            description="All processing done locally without transmitting PII externally",
            metric="privacy_compliant",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-email-delivery",
            description="Sends response emails to candidates if user opted in",
            metric="emails_handled",
            target="true",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-fabrication",
            description="Never fabricate resume content, scores, or candidate information",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-privacy",
            description="Never transmit raw resume content to external services",
            constraint_type="hard",
            category="privacy",
        ),
        Constraint(
            id="c-no-unsolicited-email",
            description="Never send emails without explicit user approval",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="c-objective-scoring",
            description="Apply scoring criteria consistently across all candidates",
            constraint_type="hard",
            category="quality",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    scan_resumes_node,
    rank_candidates_node,
    generate_report_node,
    notify_candidates_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-scan-resumes",
        source="intake",
        target="scan-resumes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="scan-resumes-to-rank-candidates",
        source="scan-resumes",
        target="rank-candidates",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="rank-candidates-to-generate-report",
        source="rank-candidates",
        target="generate-report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="generate-report-to-notify-candidates",
        source="generate-report",
        target="notify-candidates",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["notify-candidates"]


class HRScreenerAgent:
    """
    Automated HR Screener — 5-node pipeline.

    Flow: intake -> scan-resumes -> rank-candidates -> generate-report -> notify-candidates
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
        self._executor: GraphExecutor | None = None
        self._graph: GraphSpec | None = None
        self._event_bus: EventBus | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        from .nodes import _build_intake_prompt

        # Override intake prompt at runtime when env vars are set
        for node in self.nodes:
            if node.id == "intake":
                node.system_prompt = _build_intake_prompt()
                break
        return GraphSpec(
            id="hr-screener-graph",
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
            conversation_mode="continuous",
            identity_prompt="You are a rigorous and highly professional corporate human resources and engineering evaluation agent. You evaluate candidates based strictly on merit without fabrication, adhering to privacy constraints.",
            loop_config={
                "max_iterations": 50,
                "max_tool_calls_per_turn": 5,
                "max_history_tokens": 4000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "hr_screener"
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
        """Set up the agent (initialize executor and tools)."""
        if self._executor is None:
            self._setup()

    async def stop(self) -> None:
        """Clean up resources."""
        self._executor = None
        self._event_bus = None

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
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
        """Run the agent (convenience method for single execution)."""
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
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
default_agent = HRScreenerAgent()
