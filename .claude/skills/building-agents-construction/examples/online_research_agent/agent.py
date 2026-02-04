"""Agent graph construction for Online Research Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    parse_query_node,
    search_sources_node,
    fetch_content_node,
    evaluate_sources_node,
    synthesize_findings_node,
    write_report_node,
    quality_check_node,
    save_report_node,
)

# Goal definition
goal = Goal(
    id="comprehensive-online-research",
    name="Comprehensive Online Research",
    description="Research any topic by searching multiple sources, synthesizing information, and producing a well-structured narrative report with citations.",
    success_criteria=[
        SuccessCriterion(
            id="source-coverage",
            description="Query 10+ diverse sources",
            metric="source_count",
            target=">=10",
            weight=0.20,
        ),
        SuccessCriterion(
            id="relevance",
            description="All sources directly address the query",
            metric="relevance_score",
            target="90%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="synthesis",
            description="Synthesize findings into coherent narrative",
            metric="coherence_score",
            target="85%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="citations",
            description="Include citations for all claims",
            metric="citation_coverage",
            target="100%",
            weight=0.15,
        ),
        SuccessCriterion(
            id="actionable",
            description="Report answers the user's question",
            metric="answer_completeness",
            target="90%",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="no-hallucination",
            description="Only include information found in sources",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="source-attribution",
            description="Every factual claim must cite its source",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="recency-preference",
            description="Prefer recent sources when relevant",
            constraint_type="quality",
            category="relevance",
        ),
        Constraint(
            id="no-paywalled",
            description="Avoid sources that require payment to access",
            constraint_type="functional",
            category="accessibility",
        ),
    ],
)

# Node list
nodes = [
    parse_query_node,
    search_sources_node,
    fetch_content_node,
    evaluate_sources_node,
    synthesize_findings_node,
    write_report_node,
    quality_check_node,
    save_report_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="parse-to-search",
        source="parse-query",
        target="search-sources",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="search-to-fetch",
        source="search-sources",
        target="fetch-content",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="fetch-to-evaluate",
        source="fetch-content",
        target="evaluate-sources",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="evaluate-to-synthesize",
        source="evaluate-sources",
        target="synthesize-findings",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="synthesize-to-write",
        source="synthesize-findings",
        target="write-report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="write-to-quality",
        source="write-report",
        target="quality-check",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="quality-to-save",
        source="quality-check",
        target="save-report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "parse-query"
entry_points = {"start": "parse-query"}
pause_nodes = []
terminal_nodes = ["save-report"]


class OnlineResearchAgent:
    """
    Online Research Agent - Deep-dive research with narrative reports.

    Uses AgentRuntime for multi-entrypoint support with HITL pause/resume.
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
        self._runtime: AgentRuntime | None = None
        self._graph: GraphSpec | None = None

    def _build_entry_point_specs(self) -> list[EntryPointSpec]:
        """Convert entry_points dict to EntryPointSpec list."""
        specs = []
        for ep_id, node_id in self.entry_points.items():
            if ep_id == "start":
                trigger_type = "manual"
                name = "Start"
            elif "_resume" in ep_id:
                trigger_type = "resume"
                name = f"Resume from {ep_id.replace('_resume', '')}"
            else:
                trigger_type = "manual"
                name = ep_id.replace("-", " ").title()

            specs.append(
                EntryPointSpec(
                    id=ep_id,
                    name=name,
                    entry_node=node_id,
                    trigger_type=trigger_type,
                    isolation_level="shared",
                )
            )
        return specs

    def _create_runtime(self, mock_mode=False) -> AgentRuntime:
        """Create AgentRuntime instance."""
        import json
        from pathlib import Path

        # Persistent storage in ~/.hive for telemetry and run history
        storage_path = Path.home() / ".hive" / "online_research_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        tool_registry = ToolRegistry()

        # Load MCP servers (always load, needed for tool validation)
        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            tool_registry.load_mcp_config(mcp_config_path)

        llm = None
        if not mock_mode:
            # LiteLLMProvider uses environment variables for API keys
            llm = LiteLLMProvider(
                model=self.config.model,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
            )

        self._graph = GraphSpec(
            id="online-research-agent-graph",
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
        )

        # Create AgentRuntime with all entry points
        self._runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=storage_path,
            entry_points=self._build_entry_point_specs(),
            llm=llm,
            tools=list(tool_registry.get_tools().values()),
            tool_executor=tool_registry.get_executor(),
        )

        return self._runtime

    async def start(self, mock_mode=False) -> None:
        """Start the agent runtime."""
        if self._runtime is None:
            self._create_runtime(mock_mode=mock_mode)
        await self._runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime."""
        if self._runtime is not None:
            await self._runtime.stop()

    async def trigger(
        self,
        entry_point: str,
        input_data: dict,
        correlation_id: str | None = None,
        session_state: dict | None = None,
    ) -> str:
        """
        Trigger execution at a specific entry point (non-blocking).

        Args:
            entry_point: Entry point ID (e.g., "start", "pause-node_resume")
            input_data: Input data for the execution
            correlation_id: Optional ID to correlate related executions
            session_state: Optional session state to resume from (with paused_at, memory)

        Returns:
            Execution ID for tracking
        """
        if self._runtime is None or not self._runtime.is_running:
            raise RuntimeError("Agent runtime not started. Call start() first.")
        return await self._runtime.trigger(
            entry_point, input_data, correlation_id, session_state=session_state
        )

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """
        Trigger execution and wait for completion.

        Args:
            entry_point: Entry point ID
            input_data: Input data for the execution
            timeout: Maximum time to wait (seconds)
            session_state: Optional session state to resume from (with paused_at, memory)

        Returns:
            ExecutionResult or None if timeout
        """
        if self._runtime is None or not self._runtime.is_running:
            raise RuntimeError("Agent runtime not started. Call start() first.")
        return await self._runtime.trigger_and_wait(
            entry_point, input_data, timeout, session_state=session_state
        )

    async def run(
        self, context: dict, mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """
        Run the agent (convenience method for simple single execution).

        For more control, use start() + trigger_and_wait() + stop().
        """
        await self.start(mock_mode=mock_mode)
        try:
            # Determine entry point based on session_state
            if session_state and "paused_at" in session_state:
                paused_node = session_state["paused_at"]
                resume_key = f"{paused_node}_resume"
                if resume_key in self.entry_points:
                    entry_point = resume_key
                else:
                    entry_point = "start"
            else:
                entry_point = "start"

            result = await self.trigger_and_wait(
                entry_point, context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    async def get_goal_progress(self) -> dict:
        """Get goal progress across all executions."""
        if self._runtime is None:
            raise RuntimeError("Agent runtime not started")
        return await self._runtime.get_goal_progress()

    def get_stats(self) -> dict:
        """Get runtime statistics."""
        if self._runtime is None:
            return {"running": False}
        return self._runtime.get_stats()

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
            "multi_entrypoint": True,
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

        for pause in self.pause_nodes:
            if pause not in node_ids:
                errors.append(f"Pause node '{pause}' not found")

        # Validate entry points
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
default_agent = OnlineResearchAgent()
