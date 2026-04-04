"""Agent graph construction for Advanced QA Engineer Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config
from .nodes import planning_node, execution_node, ui_testing_node, reporting_node

# Define the overarching goal of the QA Agent
goal = Goal(
    id="comprehensive-qa-testing",
    name="Comprehensive QA Testing",
    description=(
        "Execute full-project QA testing including automated script execution "
        "and exploratory browser testing, culminating in a detailed bug report."
    ),
    success_criteria=[
        SuccessCriterion(
            id="test-execution",
            description="Successfully execute automated tests and parse logs.",
            metric="tests_run",
            target=">0",
            weight=0.4,
        ),
        SuccessCriterion(
            id="report-generation",
            description="Generate a detailed report with passing/failing tests.",
            metric="report_created",
            target="true",
            weight=0.6,
        ),
    ],
    constraints=[
        Constraint(
            id="safe-execution",
            description="Only execute tests inside the designated workspace sandbox.",
            constraint_type="security",
            category="safety",
        ),
    ],
)

# Register nodes (Subagents must still be registered in the graph)
nodes = [
    planning_node,
    execution_node,
    ui_testing_node,
    reporting_node,
]

# Define the workflow (Edges) - Linear flow, UI testing happens INSIDE test_execution
edges = [
    EdgeSpec(
        id="plan-to-exec",
        source="planning",
        target="test_execution",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="exec-to-report",
        source="test_execution",
        target="reporting",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="report-to-plan",
        source="reporting",
        target="planning",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="needs_more_testing == True",
        priority=1,
    ),
]

class QaEngineerAgent:
    """
    Advanced QA Engineer Agent.
    Flow: Planning -> Test Execution (w/ UI Subagent) -> Reporting -> Planning (optional loop)
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = "planning"
        self.entry_points = {"start": "planning"}
        self.terminal_nodes = ["reporting"]
        self._graph: GraphSpec | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="qa-engineer-agent-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=[],
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 50,
                "max_tool_calls_per_turn": 30,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        self._storage_path = Path.home() / ".hive" / "agents" / "qa_engineer_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()
        
        # Load external tools like browser and execute_command via MCP
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

        self._graph = self._build_graph()

        checkpoint_config = CheckpointConfig(enabled=True)

        entry_point_specs = [
            EntryPointSpec(
                id="default",
                name="Default",
                entry_node=self.entry_node,
                trigger_type="manual",
            )
        ]

        self._agent_runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=list(self._tool_registry.get_tools().values()),
            tool_executor=self._tool_registry.get_executor(),
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

    async def run(self, context: dict, mock_mode=False, session_state=None) -> ExecutionResult:
        await self.start(mock_mode=mock_mode)
        try:
            result = await self._agent_runtime.trigger_and_wait("default", context, session_state=session_state)
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

# Default instance to be exported in __init__.py
default_agent = QaEngineerAgent()