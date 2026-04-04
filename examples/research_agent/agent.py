"""Research + Summary Agent implementation."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    research_node,
    extraction_node,
    summarize_node,
)

# Goal definition
goal = Goal(
    id="research-and-summarize",
    name="Research and Summarize",
    description="Gather information on a topic, extract key points, and produce a structured summary.",
)

# Node list
nodes = [
    research_node,
    extraction_node,
    summarize_node,
]

# Edge definitions (Sequential pipeline)
edges = [
    # gather_info -> extract_points
    EdgeSpec(
        id="research-to-extract",
        source="gather_info",
        target="extract_points",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # extract_points -> summarize
    EdgeSpec(
        id="extract-to-summarize",
        source="extract_points",
        target="summarize",
        condition=EdgeCondition.ON_SUCCESS,
    ),
]

# Graph configuration
entry_node = "gather_info"
entry_points = {"start": "gather_info"}
terminal_nodes = ["summarize"]


class ResearchAgent:
    """
    Research + Summary Agent pipeline.
    Flow: gather_info -> extract_points -> summarize
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.terminal_nodes = terminal_nodes
        self._graph: GraphSpec | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="research-summary-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 20,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 16000,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "research_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

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

        checkpoint_config = CheckpointConfig(enabled=False)

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
            storage_path=storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
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

    async def run(self, context: dict, mock_mode=False) -> ExecutionResult:
        await self.start(mock_mode=mock_mode)
        try:
            result = await self._agent_runtime.trigger_and_wait(
                entry_point_id="default",
                input_data=context,
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "nodes": [n.id for n in self.nodes],
            "client_facing_nodes": [n.id for n in self.nodes if getattr(n, 'client_facing', False)],
            "entry_node": self.entry_node,
            "terminal_nodes": self.terminal_nodes,
        }

default_agent = ResearchAgent()
