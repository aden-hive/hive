"""Agent graph construction for Hive Dev Loop."""

import sys
from pathlib import Path



root_dir = Path(__file__).resolve().parents[4]
if str(root_dir / "core") not in sys.path:
    sys.path.append(str(root_dir / "core"))

from framework.graph import (  # noqa: E402
    EdgeSpec,
    EdgeCondition,
    Goal,
    SuccessCriterion,
    Constraint,
    GraphSpec,
)
from framework.graph.executor import ExecutionResult, GraphExecutor  # noqa: E402
from framework.runtime.event_bus import EventBus  # noqa: E402
from framework.runtime.core import Runtime  # noqa: E402
from framework.llm import LiteLLMProvider  # noqa: E402
from framework.runner.tool_registry import ToolRegistry  # noqa: E402

from .config import default_config, metadata  # noqa: E402
from .nodes import (  # noqa: E402
    plan_node,
    write_test_node,
    write_code_node,
    run_pytest_node,
    debug_node,
    report_node,
)

# Goal definition
goal = Goal(
    id="autonomous-tdd-loop",
    name="Autonomous TDD Developer",
    description=(
        "Execute a full Test-Driven Development (TDD) cycle: "
        "Strategic Planning -> Test Creation -> Implementation -> Automated Refactoring."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-tests-pass",
            description="All unit tests pass successfully",
            metric="test_status",
            target="PASS",
            weight=1.0,
        )
    ],
    constraints=[
        Constraint(
            id="c-valid-python",
            description="Code must be valid Python syntax",
            constraint_type="hard",
            category="syntax",
        ),
        Constraint(
            id="c-tdd-process",
            description="Tests must be written before implementation",
            constraint_type="soft",
            category="process",
        ),
    ],
)

# Node list
nodes = [
    plan_node,
    write_test_node,
    write_code_node,
    run_pytest_node,
    debug_node,
    report_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="p-t",
        source="plan",
        target="write_test",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="t-c",
        source="write_test",
        target="write_code",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="c-r",
        source="write_code",
        target="run_pytest",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="r-d",
        source="run_pytest",
        target="debugger",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="test_status == 'FAIL'",
        priority=1,
    ),
    EdgeSpec(
        id="d-c",
        source="debugger",
        target="write_code",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="r-rep",
        source="run_pytest",
        target="report",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="test_status == 'PASS'",
        priority=1,
    ),
]

# Graph configuration
entry_node = "plan"
entry_points = {"start": "plan"}
pause_nodes = []
terminal_nodes = ["report"]


class HiveDevLoopAgent:
    """
    Hive Dev Loop Agent — Professional TDD pipeline implementation.

    Flow: plan -> write_test -> write_code -> run_pytest -> (debugger <-> write_code) -> report
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
            id="hive-dev-loop-graph",
            goal_id=self.goal.id,
            version="2.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 50,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "hive_dev_loop" / "workspace"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        # Initialize LLM Provider
        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )

        # Register Tools
        try:
            from aden_tools.tools.file_system_toolkits.write_to_file.write_to_file import (  # noqa: E402
                write_to_file,
            )
            from aden_tools.tools.file_system_toolkits.view_file.view_file import (  # noqa: E402
                view_file,
            )
            from aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool import (  # noqa: E402
                execute_command_tool,
            )

            self._tool_registry.register_function(write_to_file)
            self._tool_registry.register_function(view_file)
            self._tool_registry.register_function(execute_command_tool)
        except ImportError:
            print(
                "[System] Standard tools not found. Agent capabilities may be limited."
            )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()
        runtime = Runtime(storage_path)

        # Professional Runtime Setup
        runtime.set_default_llm(llm)

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
            "intro_message": metadata.intro_message,
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
default_agent = HiveDevLoopAgent()