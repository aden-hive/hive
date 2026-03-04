"""Agent graph construction for Data Analysis Agent."""

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
from .nodes import intake_node, analysis_node, report_node

# Goal definition
goal = Goal(
    id="dataset-analysis",
    name="Dataset Analysis",
    description="Analyze a dataset and generate statistical insights.",
)


# Node list
nodes = [
    intake_node,
    analysis_node,
    report_node,
]


# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-analysis",
        source="intake",
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
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []


class DataAnalysisAgent:
    """
    Data Analysis Agent

    Flow: intake -> analysis -> report
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

        self._graph: GraphSpec | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="data-analysis-agent-graph",
            goal_id=self.goal.id,
            version="0.1.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up runtime components."""

        storage_path = Path.home() / ".hive" / "agents" / "data_analysis_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

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
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=7,
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
            storage_path=storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
        )

    async def start(self, mock_mode=False) -> None:
        """Start the agent runtime."""
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop runtime."""
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()

    async def run(self, context: dict) -> ExecutionResult:
        """Run the agent once."""
        await self.start()
        try:
            result = await self._agent_runtime.trigger_and_wait(
                entry_point_id="default",
                input_data=context,
            )
            return result
        finally:
            await self.stop()


# Create default instance
default_agent = DataAnalysisAgent()
