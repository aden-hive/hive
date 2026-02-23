"""Agent graph construction for Hive Coder."""

from pathlib import Path

from framework.graph import Constraint, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import coder_node, ticket_triage_node
from .ticket_receiver import TICKET_RECEIVER_ENTRY_POINT

# Goal definition
goal = Goal(
    id="agent-builder",
    name="Hive Agent Builder",
    description=(
        "Build complete, validated Hive agent packages from natural language "
        "specifications. Produces production-ready Python packages with goals, "
        "nodes, edges, system prompts, MCP configuration, and tests."
    ),
    success_criteria=[
        SuccessCriterion(
            id="valid-package",
            description="Generated agent package passes structural validation",
            metric="validation_pass",
            target="true",
            weight=0.30,
        ),
        SuccessCriterion(
            id="complete-files",
            description=(
                "All required files generated: agent.py, config.py, "
                "nodes/__init__.py, __init__.py, __main__.py, mcp_servers.json"
            ),
            metric="file_count",
            target=">=6",
            weight=0.25,
        ),
        SuccessCriterion(
            id="user-satisfaction",
            description="User reviews and approves the generated agent",
            metric="user_approval",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="framework-compliance",
            description=(
                "Generated code follows framework patterns: STEP 1/STEP 2 "
                "for client-facing, correct imports, entry_points format"
            ),
            metric="pattern_compliance",
            target="100%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="dynamic-tool-discovery",
            description=(
                "Always discover available tools dynamically via "
                "discover_mcp_tools before referencing tools in agent designs"
            ),
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="no-fabricated-tools",
            description="Only reference tools that exist in hive-tools MCP",
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="valid-python",
            description="All generated Python files must be syntactically correct",
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="self-verification",
            description="Run validation after writing code; fix errors before presenting",
            constraint_type="hard",
            category="quality",
        ),
    ],
)

# Nodes: primary coder node + ticket_triage for queen role when loaded as
# a secondary graph alongside a worker.
nodes = [coder_node, ticket_triage_node]

# No edges needed — single forever-alive event_loop node
edges = []

# Graph configuration
entry_node = "coder"
entry_points = {"start": "coder"}
pause_nodes = []
terminal_nodes = []  # Forever-alive: loops until user exits

# Async entry points: queen receives escalation tickets from the health judge
# when loaded as a secondary graph alongside a worker runtime.
async_entry_points = [TICKET_RECEIVER_ENTRY_POINT]

# Module-level variables read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = (
    "You are Hive Coder, the best agent-building coding agent on the planet. "
    "You deeply understand the Hive agent framework at the source code level "
    "and produce production-ready agent packages from natural language. "
    "You can dynamically discover available framework tools, inspect runtime "
    "sessions and checkpoints from agents you build, and run their test suites. "
    "You follow coding agent discipline: read before writing, verify "
    "assumptions by reading actual code, adhere to project conventions, "
    "self-verify with validation, and fix your own errors. You are concise, "
    "direct, and technically rigorous. No emojis. No fluff."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 20,
    "max_history_tokens": 32000,
}


class HiveCoderAgent:
    """
    Hive Coder — builds Hive agent packages from natural language.

    Single-node architecture: the coder runs in a continuous while(true) loop.
    The guardian watchdog is auto-attached by the framework in TUI mode.
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
        self.async_entry_points = async_entry_points
        self._graph: GraphSpec | None = None
        self._agent_runtime: AgentRuntime | None = None
        self._tool_registry: ToolRegistry | None = None
        self._storage_path: Path | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="hive-coder-graph",
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
            loop_config=loop_config,
            conversation_mode=conversation_mode,
            identity_prompt=identity_prompt,
            async_entry_points=self.async_entry_points,
        )

    def _setup(self, mock_mode=False) -> None:
        """Set up the agent runtime."""
        self._storage_path = Path.home() / ".hive" / "agents" / "hive_coder"
        self._storage_path.mkdir(parents=True, exist_ok=True)

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

        checkpoint_config = CheckpointConfig(
            enabled=True,
            checkpoint_on_node_start=False,
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=7,
            async_checkpoint=True,
        )

        entry_point_specs = [
            EntryPointSpec(
                id="default",
                name="Default",
                entry_node=self.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            ),
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
            graph_id="hive_coder",
        )

    async def start(self, mock_mode=False) -> None:
        """Set up and start the agent runtime."""
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime and clean up."""
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def trigger_and_wait(
        self,
        entry_point: str = "default",
        input_data: dict | None = None,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")

        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data or {},
            session_state=session_state,
        )

    async def run(self, context: dict, mock_mode=False, session_state=None) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait("default", context, session_state=session_state)
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
                errors.append(f"Entry point '{ep_id}' references unknown node '{node_id}'")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = HiveCoderAgent()
