"""Agent graph construction for Logistics Navigation Agent (Caitlyn)."""

from typing import Any, TYPE_CHECKING
from framework.graph import (
    EdgeSpec,
    EdgeCondition,
    Goal,
    SuccessCriterion,
    NodeSpec,
)
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    intake_node,
    poi_search_node,
    navigation_node,
)

if TYPE_CHECKING:
    from framework.config import RuntimeConfig

# Goal definition
goal: Goal = Goal(
    id="logistics-navigation",
    name="Logistics Navigation",
    description="Plan and execute a multi-stop route based on natural language requests.",
    success_criteria=[
        SuccessCriterion(
            id="sc-stops-resolved",
            description="All requested POIs are resolved to coordinates.",
            metric="pois_resolved",
            target="true",
            weight=0.5,
        ),
        SuccessCriterion(
            id="sc-nav-triggered",
            description="Navigation tool is called with structured data.",
            metric="nav_active",
            target="true",
            weight=0.5,
        ),
    ],
)

nodes: list[NodeSpec] = [
    intake_node,
    poi_search_node,
    navigation_node,
]

edges: list[EdgeSpec] = [
    EdgeSpec(
        id="intake-to-poi",
        source="intake",
        target="poi-search",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="poi-to-nav",
        source="poi-search",
        target="navigation",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node: str = "intake"
terminal_nodes: list[str] = ["navigation"]

class LogisticsNavAgent:
    def __init__(self, config=None) -> None:
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.terminal_nodes = terminal_nodes
        self._executor = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="logistics-nav-agent-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            terminal_nodes=self.terminal_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            loop_config={
                "max_iterations": 20,
                "max_tool_calls_per_turn": 10,
            },
        )

    def _setup(self) -> GraphExecutor:
        from pathlib import Path
        storage_path = Path.home() / ".hive" / "agents" / "logistics_nav_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        llm = LiteLLMProvider(
            model=self.config.model,
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
        )

        return self._executor

    async def run(self, context: dict[str, Any]) -> ExecutionResult:
        if self._executor is None:
            self._setup()
        return await self._executor.execute(
            graph=self._graph,
            goal=self.goal,
            input_data=context
        )

default_agent = LogisticsNavAgent()
