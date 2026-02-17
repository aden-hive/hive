"""Agent graph construction for Salesforce Manager Agent."""

from pathlib import Path
from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import AgentMetadata
from .nodes import (
    intake_node,
    salesforce_manager_node,
    output_node,
)

class Config:
    def __init__(self):
        self.model = "claude-3-5-sonnet-latest"
        self.api_key = None
        self.api_base = None
        self.max_tokens = 4096

default_config = Config()
metadata = AgentMetadata()

# Goal definition
goal = Goal(
    id="salesforce-management",
    name="Salesforce CRM Management",
    description="Manage Salesforce records and perform queries to surface business insights.",
    success_criteria=[
        SuccessCriterion(
            id="task-completion",
            description="The requested Salesforce task is executed successfully",
            metric="completion_rate",
            target="100%",
            weight=0.5,
        ),
        SuccessCriterion(
            id="data-accuracy",
            description="Retrieved data matches user search criteria",
            metric="accuracy",
            target="high",
            weight=0.5,
        ),
    ],
    constraints=[
        Constraint(
            id="read-only-if-requested",
            description="Do not modify records unless explicitly asked",
            constraint_type="functional",
            category="safety",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    salesforce_manager_node,
    output_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-manager",
        source="intake",
        target="salesforce_manager",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="manager-to-output",
        source="salesforce_manager",
        target="output",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="output-to-intake",
        source="output",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="next_action == 'new_task'",
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []

class SalesforceManagerAgent:
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
            id="salesforce-manager-graph",
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

    def _setup(self, mock_mode: bool = False) -> None:
        self._storage_path = Path.home() / ".hive" / "agents" / "salesforce_manager"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()
        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        llm = None
        if not mock_mode:
            llm = LiteLLMProvider(model=self.config.model)

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()

        checkpoint_config = CheckpointConfig(enabled=True)
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
        )

    async def start(self, mock_mode=False) -> None:
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def trigger_and_wait(self, entry_point="default", input_data=None):
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started.")
        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data or {},
        )

    async def stop(self) -> None:
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None
