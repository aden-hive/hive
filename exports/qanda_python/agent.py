"""Agent definition for the Q&A Agent."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import generate_answer_node

# Goal definition
goal = Goal(
    id="q_and_a_goal",
    name="Answer Questions Effectively",
    description="Provide clear and helpful answers to user questions.",
    success_criteria=[
        SuccessCriterion(
            id="sc1",
            description="The user receives a clear and understandable answer.",
            metric="user_satisfaction",
            target="high",
            weight=1.0,
        )
    ],
    constraints=[],
)

# Node list
nodes = [
    generate_answer_node,
]

# Edge definitions (empty for single node graph)
edges = []

# Graph configuration
entry_node = "generate_answer"
entry_points = {"start": "generate_answer"}
pause_nodes = []
terminal_nodes = ["generate_answer"]


class QandAAgent:
    """A single-node agent for answering questions effectively.

    This agent is designed to take a question as input and generate a clear,
    understandable answer using an LLM.

    Attributes:
        config: The runtime configuration for the agent.
        goal: The goal object defining the agent's objective.
        nodes: A list of nodes in the agent's graph.
        edges: A list of edges defining transitions between nodes.
        entry_node: The ID of the starting node.
        entry_points: A mapping of entry point IDs to node IDs.
        pause_nodes: A list of node IDs where execution can pause.
        terminal_nodes: A list of node IDs that end execution.
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
        """Builds the GraphSpec for the agent.

        Returns:
            GraphSpec: The configured graph specification.
        """
        return GraphSpec(
            id="q_and_a_agent_graph",
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
                "max_iterations": 10,
                "max_tool_calls_per_turn": 5,
                "max_history_tokens": 8000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Sets up the graph executor with all necessary components.

        Initializes storage, event bus, tool registry, LLM provider, and runtime.

        Returns:
            GraphExecutor: The configured executor ready for running graphs.
        """
        storage_path = Path.home() / ".hive" / "agents" / "qanda_python"
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
        input_data: Dict[str, Any],
        timeout: Optional[float] = None,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[ExecutionResult]:
        """Executes the graph and waits for completion.

        Args:
            entry_point: The ID of the entry point to start from.
            input_data: The input data for the execution.
            timeout: Optional timeout in seconds.
            session_state: Optional initial session state.

        Returns:
            Optional[ExecutionResult]: The result of the execution, or None if it timed out.

        Raises:
            RuntimeError: If the agent has not been started.
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
        self, context: Dict[str, Any], session_state: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        """Runs the agent for a single execution.

        This is a convenience method that handles start and stop automatically.

        Args:
            context: The input context (data) for the agent.
            session_state: Optional initial session state.

        Returns:
            ExecutionResult: The result of the agent execution.
        """
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> Dict[str, Any]:
        """Gets information about the agent's structure and metadata.

        Returns:
            Dict[str, Any]: A dictionary containing agent metadata and graph details.
        """
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

    def validate(self) -> Dict[str, Any]:
        """Validates the agent's graph structure for consistency.

        Checks if all edges reference existing nodes and if the entry node is valid.

        Returns:
            Dict[str, Any]: A dictionary containing 'valid' boolean, and lists of
                'errors' and 'warnings'.
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
default_agent = QandAAgent()
