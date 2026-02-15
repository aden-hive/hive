"""Agent graph construction for Inbox Management Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    intake_node,
    fetch_emails_node,
    classify_and_act_node,
    report_node,
)

# Goal definition
goal = Goal(
    id="inbox-management",
    name="Inbox Management",
    description=(
        "Manage Gmail inbox emails using user-defined free-text rules. "
        "Fetch inbox emails (configurable batch size, default 100), apply the user's "
        "rules to each email, and execute the appropriate Gmail actions — trash, "
        "mark as spam, mark important, mark read/unread, star, and more."
    ),
    success_criteria=[
        SuccessCriterion(
            id="correct-action-execution",
            description=(
                "Gmail actions are applied correctly to the right emails "
                "based on the user's rules"
            ),
            metric="action_correctness",
            target=">=95%",
            weight=0.35,
        ),
        SuccessCriterion(
            id="action-report",
            description=(
                "Produces a summary report showing what was done: how many emails "
                "were affected by each action type, with email subjects listed"
            ),
            metric="report_completeness",
            target="100%",
            weight=0.3,
        ),
        SuccessCriterion(
            id="batch-completeness",
            description=(
                "All fetched emails up to the configured max are processed and acted upon; "
                "none are silently skipped"
            ),
            metric="emails_processed_ratio",
            target="100%",
            weight=0.35,
        ),
    ],
    constraints=[
        Constraint(
            id="respect-batch-limit",
            description="Must not process more emails than the configured max_emails parameter",
            constraint_type="hard",
            category="operational",
        ),
        Constraint(
            id="non-destructive-default",
            description=(
                "Archiving removes from inbox but preserves the email; only explicit "
                "trash rules move emails to trash"
            ),
            constraint_type="hard",
            category="safety",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    fetch_emails_node,
    classify_and_act_node,
    report_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-fetch-emails",
        source="intake",
        target="fetch-emails",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="fetch-emails-to-classify",
        source="fetch-emails",
        target="classify-and-act",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-report",
        source="classify-and-act",
        target="report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="report-to-intake",
        source="report",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 50,
    "max_history_tokens": 32000,
}


class InboxManagementAgent:
    """
    Inbox Management Agent — continuous 4-node pipeline for email triage.

    Flow: intake -> fetch-emails -> classify-and-act -> report -> intake (loop)
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
            id="inbox-management-graph",
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
            conversation_mode="continuous",
            identity_prompt=(
                "You are an inbox management assistant. You help users manage "
                "their Gmail inbox by applying free-text rules to emails — trash, "
                "mark as spam, mark important, mark read/unread, star, and more."
            ),
        )

    def _setup(self, mock_mode=False) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "agents" / "inbox_management"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        # Discover custom script tools (e.g. bulk_fetch_emails)
        tools_path = Path(__file__).parent / "tools.py"
        if tools_path.exists():
            self._tool_registry.discover_from_module(tools_path)

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

    async def start(self, mock_mode=False) -> None:
        """Set up the agent (initialize executor and tools)."""
        if self._executor is None:
            self._setup(mock_mode=mock_mode)

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

    async def run(
        self, context: dict, mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
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
default_agent = InboxManagementAgent()
