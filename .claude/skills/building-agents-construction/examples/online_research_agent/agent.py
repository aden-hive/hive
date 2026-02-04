"""Agent graph construction for Online Research Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
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

    Uses GraphExecutor directly with EventLoopNode instances registered
    in the node_registry for multi-turn tool execution.
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
        return GraphSpec(
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

    def _build_node_registry(self, tool_executor=None) -> dict:
        """Create EventLoopNode instances for all event_loop nodes."""
        registry = {}
        for node_spec in self.nodes:
            if node_spec.node_type == "event_loop":
                registry[node_spec.id] = EventLoopNode(
                    event_bus=self._event_bus,
                    judge=None,  # implicit judge: accept when output_keys are filled
                    config=LoopConfig(
                        max_iterations=50,
                        max_tool_calls_per_turn=15,
                        stall_detection_threshold=3,
                        max_history_tokens=32000,
                    ),
                    tool_executor=tool_executor,
                )
        return registry

    def _setup(self, mock_mode=False) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "online_research_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
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
        node_registry = self._build_node_registry(tool_executor=tool_executor)
        runtime = Runtime(storage_path)

        self._executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            node_registry=node_registry,
        )

        return self._executor

    async def start(self, mock_mode=False) -> None:
        """Set up the agent (initialize executor and tools)."""
        if self._executor is None:
            self._setup(mock_mode=mock_mode)

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

    async def run(
        self, context: dict, mock_mode=False, session_state=None
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
