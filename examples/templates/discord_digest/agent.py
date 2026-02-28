"""Agent graph construction for Discord Community Digest."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    configure_node,
    scan_channels_node,
    generate_digest_node,
)

# Goal definition
goal = Goal(
    id="discord-digest",
    name="Discord Community Digest",
    description=(
        "Monitor Discord servers, categorize messages by priority, "
        "and deliver an actionable summary as a Discord DM."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-channels-scanned",
            description="At least 5 channels are scanned for messages",
            metric="channels_scanned",
            target=">=5",
            weight=0.20,
        ),
        SuccessCriterion(
            id="sc-messages-categorized",
            description="Messages are categorized into action/threads/announcements/fyi",
            metric="messages_categorized",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-digest-delivered",
            description="Digest is delivered as a Discord DM to the user",
            metric="digest_delivered",
            target="true",
            weight=0.30,
        ),
        SuccessCriterion(
            id="sc-dedup",
            description="Digest does not repeat messages from previous runs",
            metric="dedup_applied",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-spam",
            description="Never send unsolicited messages to other users",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="c-time-range",
            description="Only scan messages within the configured lookback window",
            constraint_type="hard",
            category="correctness",
        ),
        Constraint(
            id="c-rate-limit",
            description="Respect Discord API rate limits",
            constraint_type="hard",
            category="reliability",
        ),
    ],
)

# Node list
nodes = [
    configure_node,
    scan_channels_node,
    generate_digest_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="configure-to-scan",
        source="configure",
        target="scan-channels",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
        description="After capturing preferences, scan Discord channels",
    ),
    EdgeSpec(
        id="scan-to-digest",
        source="scan-channels",
        target="generate-digest",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
        description="After scanning channels, generate and deliver the digest",
    ),
]

# Graph configuration
entry_node = "configure"
entry_points = {"start": "configure"}
pause_nodes = []
terminal_nodes = ["generate-digest"]


class DiscordDigestAgent:
    """
    Discord Community Digest — 3-node pipeline.

    Flow: configure -> scan-channels -> generate-digest
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
            id="discord-digest-graph",
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
                "max_iterations": 50,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "discord_digest"
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
default_agent = DiscordDigestAgent()
