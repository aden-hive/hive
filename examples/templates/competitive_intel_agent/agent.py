"""Agent graph construction for Competitive Intelligence Agent."""

from typing import Any, TYPE_CHECKING
from framework.graph import (
    EdgeSpec,
    EdgeCondition,
    Goal,
    SuccessCriterion,
    Constraint,
    NodeSpec,
)
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata, RuntimeConfig
from .nodes import (
    intake_node,
    web_scraper_node,
    news_search_node,
    github_monitor_node,
    aggregator_node,
    analysis_node,
    report_node,
)

if TYPE_CHECKING:
    from framework.config import RuntimeConfig

# Goal definition
goal: Goal = Goal(
    id="competitive-intelligence-report",
    name="Competitive Intelligence Report",
    description=(
        "Monitor competitor websites, news sources, and GitHub repositories "
        "to produce a structured weekly digest with key insights, detailed "
        "findings per competitor, and 30-day trend analysis."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-source-coverage",
            description="Check multiple source types per competitor (website, news, GitHub)",
            metric="sources_per_competitor",
            target=">=3",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-findings-structured",
            description="All findings structured with competitor, category, update, source, and date",
            metric="findings_structured",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-historical-comparison",
            description="Uses stored data to compare with previous reports for trend analysis",
            metric="historical_comparison",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-report-delivered",
            description="User receives a formatted, readable competitive intelligence digest",
            metric="report_delivered",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-fabrication",
            description="Never fabricate findings, news, or data — only report what was found",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-source-attribution",
            description="Every finding must include a source URL",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-recency",
            description="Prioritize findings from the past 7 days; include up to 30 days",
            constraint_type="soft",
            category="quality",
        ),
    ],
)

# Node list
nodes: list[NodeSpec] = [
    intake_node,
    web_scraper_node,
    news_search_node,
    github_monitor_node,
    aggregator_node,
    analysis_node,
    report_node,
]

# Edge definitions
edges: list[EdgeSpec] = [
    EdgeSpec(
        id="intake-to-web-scraper",
        source="intake",
        target="web-scraper",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="web-scraper-to-news-search",
        source="web-scraper",
        target="news-search",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="news-search-to-github-monitor",
        source="news-search",
        target="github-monitor",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(has_github_competitors).lower() == 'true'",
        priority=2,
    ),
    EdgeSpec(
        id="news-search-to-aggregator-skip-github",
        source="news-search",
        target="aggregator",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(has_github_competitors).lower() != 'true'",
        priority=1,
    ),
    EdgeSpec(
        id="github-monitor-to-aggregator",
        source="github-monitor",
        target="aggregator",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="aggregator-to-analysis",
        source="aggregator",
        target="analysis",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="analysis-to-report",
        source="analysis",
        target="report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node: str = "intake"
entry_points: dict[str, str] = {"start": "intake"}
pause_nodes: list[str] = []
terminal_nodes: list[str] = ["report"]


class CompetitiveIntelAgent:
    """
    Competitive Intelligence Agent — 7-node pipeline.

    Flow: intake -> web-scraper -> news-search -> github-monitor -> aggregator -> analysis -> report
                                                       |
                                            (skipped if no GitHub competitors)
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        """
        Initialize the Competitive Intelligence Agent.

        Args:
            config: Optional runtime configuration. Defaults to default_config.
        """
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
        """
        Build the GraphSpec for the competitive intelligence workflow.

        Returns:
            A GraphSpec defining the agent's logic.
        """
        return GraphSpec(
            id="competitive-intel-agent-graph",
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
                "max_iterations": 100,
                "max_tool_calls_per_turn": 20,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """
        Set up the executor with all components (runtime, LLM, tools).

        Returns:
            An initialized GraphExecutor instance.
        """
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "agents" / "competitive_intel_agent"
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
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """
        Execute the graph and wait for completion.

        Args:
            entry_point: The graph entry point to trigger.
            input_data: Data to pass to the entry node.
            timeout: Optional execution timeout.
            session_state: Optional initial session state.

        Returns:
            The execution result, or None if it timed out.
        """
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

    async def run(
        self, context: dict[str, Any], session_state: dict[str, Any] | None = None
    ) -> ExecutionResult:
        """
        Run the agent (convenience method for single execution).

        Args:
            context: The input context for the agent.
            session_state: Optional initial session state.

        Returns:
            The final execution result.
        """
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> dict[str, Any]:
        """Get agent information for introspection."""
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

    def validate(self) -> dict[str, Any]:
        """
        Validate agent structure for cycles, missing nodes, or invalid edges.

        Returns:
            A dict with 'valid' (bool), 'errors' (list), and 'warnings' (list).
        """
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
default_agent: CompetitiveIntelAgent = CompetitiveIntelAgent()
