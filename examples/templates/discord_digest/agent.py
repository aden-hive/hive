"""Agent graph construction for Discord Community Digest."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    configure_node,
    scan_channels_node,
    generate_digest_node,
)

# Goal definition
goal = Goal(
    id="discord-digest-goal",
    name="Discord Community Digest",
    description=(
        "Monitor Discord servers, categorize messages by priority, "
        "and deliver an actionable summary to a designated channel."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-channels-scanned",
            description="All target text channels are scanned for messages",
            metric="channels_scanned",
            target=">=1",
            weight=0.3,
        ),
        SuccessCriterion(
            id="sc-messages-categorized",
            description="Messages categorized into Action Needed / Interesting Threads / Announcements / FYI",
            metric="categorization_complete",
            target="true",
            weight=0.3,
        ),
        SuccessCriterion(
            id="sc-digest-delivered",
            description="Digest delivered to the configured Discord channel",
            metric="digest_delivered",
            target="true",
            weight=0.4,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-spam",
            description="Never send unsolicited messages to users or channels not configured for delivery",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="c-lookback-window",
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
    ),
    EdgeSpec(
        id="scan-to-digest",
        source="scan-channels",
        target="generate-digest",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "configure"
entry_points = {"start": "configure"}
pause_nodes = []
terminal_nodes = ["generate-digest"]

# Module-level vars read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = (
    "You are a Discord community digest assistant. You scan Discord servers, "
    "categorize messages by urgency and engagement, and deliver concise "
    "actionable summaries."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class DiscordDigestAgent:
    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._graph = None
        self._agent_runtime = None
        self._tool_registry = None
        self._storage_path = None

    def _build_graph(self):
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
            loop_config=loop_config,
            conversation_mode=conversation_mode,
            identity_prompt=identity_prompt,
        )

    def _setup(self):
        self._storage_path = Path.home() / ".hive" / "agents" / "discord_digest"
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._tool_registry = ToolRegistry()
        mcp_config = Path(__file__).parent / "mcp_servers.json"
        if mcp_config.exists():
            self._tool_registry.load_mcp_config(mcp_config)
        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()
        self._graph = self._build_graph()
        self._agent_runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=[
                EntryPointSpec(
                    id="default",
                    name="Default",
                    entry_node=self.entry_node,
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(
                enabled=True,
                checkpoint_on_node_complete=True,
                checkpoint_max_age_days=7,
                async_checkpoint=True,
            ),
        )

    async def start(self):
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self):
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def trigger_and_wait(
        self,
        entry_point="default",
        input_data=None,
        timeout=None,
        session_state=None,
    ):
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")
        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data or {},
            session_state=session_state,
        )

    async def run(self, context, session_state=None):
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
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
            "terminal_nodes": self.terminal_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self):
        errors, warnings = [], []
        node_ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in node_ids:
                errors.append(f"Edge {e.id}: source '{e.source}' not found")
            if e.target not in node_ids:
                errors.append(f"Edge {e.id}: target '{e.target}' not found")
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        for t in self.terminal_nodes:
            if t not in node_ids:
                errors.append(f"Terminal node '{t}' not found")
        for ep_id, nid in self.entry_points.items():
            if nid not in node_ids:
                errors.append(f"Entry point '{ep_id}' references unknown node '{nid}'")
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = DiscordDigestAgent()
