"""Agent graph construction for Gmail Inbox Guardian."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec, AsyncEntryPointSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    intake_node,
    fetch_emails_node,
    classify_and_act_node,
    report_node,
)

# Goal definition
goal = Goal(
    id="gmail-inbox-guardian",
    name="Gmail Inbox Guardian",
    description=(
        "An event-driven Gmail inbox agent. The user defines free-text rules for "
        "email triage (e.g., 'star emails from my boss', 'spam marketing newsletters'). "
        "When triggered by external events (webhooks, manual triggers), the agent fetches "
        "new emails, classifies each one against the user's rules, executes the appropriate "
        "Gmail actions, and reports what was done."
    ),
    success_criteria=[
        SuccessCriterion(
            id="rule-understanding",
            description="Correctly interprets user free-text rules and maps them to Gmail actions",
            metric="rule_accuracy",
            target=">=95%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="action-execution",
            description="Gmail actions are applied to the correct emails based on rule matching",
            metric="action_correctness",
            target=">=95%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="batch-completeness",
            description="All fetched emails are processed; none silently skipped",
            metric="emails_processed_ratio",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="summary-report",
            description=(
                "Produces a clear report of actions taken grouped by action type "
                "with email subjects and senders"
            ),
            metric="report_completeness",
            target="100%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="non-destructive-default",
            description=(
                "Archiving removes from inbox but preserves email; only explicit "
                "trash/spam rules move emails to trash/spam"
            ),
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="respect-batch-limit",
            description="Must not process more emails than the configured max_emails parameter",
            constraint_type="hard",
            category="operational",
        ),
        Constraint(
            id="shared-rule-state",
            description=(
                "Rules must persist in shared memory so event-driven executions "
                "can access them without re-asking the user"
            ),
            constraint_type="hard",
            category="architectural",
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
    # intake -> intake (self-loop: user stays here to tweak rules)
    EdgeSpec(
        id="intake-to-intake",
        source="intake",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # fetch-emails -> classify-and-act (event-driven path only)
    EdgeSpec(
        id="fetch-emails-to-classify",
        source="fetch-emails",
        target="classify-and-act",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # classify-and-act -> report
    EdgeSpec(
        id="classify-to-report",
        source="classify-and-act",
        target="report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
async_entry_points = [
    AsyncEntryPointSpec(
        id="email-event",
        name="Email Event Handler",
        entry_node="fetch-emails",
        trigger_type="event",
        trigger_config={"event_types": ["webhook_received"]},
        isolation_level="shared",
        max_concurrent=10,
    ),
    AsyncEntryPointSpec(
        id="email-timer",
        name="Scheduled Inbox Check",
        entry_node="fetch-emails",
        trigger_type="timer",
        trigger_config={"interval_minutes": 20},
        isolation_level="shared",
        max_concurrent=1,
    ),
]
pause_nodes = []
terminal_nodes = []
conversation_mode = "continuous"
identity_prompt = (
    "You are an inbox management assistant. You help users manage their "
    "Gmail inbox by applying free-text rules to emails — trash, mark as spam, "
    "mark important, mark read/unread, star, and more."
)
runtime_config = AgentRuntimeConfig(
    webhook_host="127.0.0.1",
    webhook_port=8080,
    webhook_routes=[
        {
            "source_id": "gmail",
            "path": "/webhooks/gmail",
            "methods": ["POST"],
        },
    ],
)


class GmailInboxGuardianAgent:
    """
    Gmail Inbox Guardian — event-driven email triage agent.

    Primary:  intake ↻ (forever-alive, user tweaks rules)
    Async:    fetch-emails -> classify-and-act -> report (per event/timer trigger)

    Entry Points:
    - "start" (primary): User sets up triage rules via intake node
    - "email-event" (async): External events trigger fetch-emails directly
    - "email-timer" (timer): Scheduled inbox check every 20 minutes

    Uses AgentRuntime for:
    - Multi-entry-point execution (primary + event-driven + timer)
    - Session-scoped storage (sessions/{session_id}/)
    - Shared state for rules persistence across entry points
    - Checkpointing for resume capability
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
            id="gmail-inbox-guardian-graph",
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
            conversation_mode="continuous",
            identity_prompt=(
                "You are an inbox management assistant. You help users manage their "
                "Gmail inbox by applying free-text rules to emails — trash, mark as spam, "
                "mark important, mark read/unread, star, and more."
            ),
            async_entry_points=[
                AsyncEntryPointSpec(
                    id="email-event",
                    name="Email Event Handler",
                    entry_node="fetch-emails",
                    trigger_type="event",
                    trigger_config={
                        "event_types": ["webhook_received"],
                    },
                    isolation_level="shared",
                    max_concurrent=10,
                ),
            ],
        )

    def _setup(self, mock_mode=False) -> None:
        """Set up the agent runtime with sessions, checkpoints, and logging."""
        self._storage_path = Path.home() / ".hive" / "agents" / "gmail_inbox_guardian"
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

        # Primary entry point (user-facing rule setup)
        entry_point_specs = [
            EntryPointSpec(
                id="default",
                name="Rule Setup",
                entry_node=self.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            ),
            # Event-driven entry point (triggered by external events)
            EntryPointSpec(
                id="email-event",
                name="Email Event Handler",
                entry_node="fetch-emails",
                trigger_type="event",
                trigger_config={
                    "event_types": ["webhook_received"],
                },
                isolation_level="shared",
                max_concurrent=10,
            ),
            # Scheduled entry point (fires every 20 minutes)
            EntryPointSpec(
                id="email-timer",
                name="Scheduled Inbox Check",
                entry_node="fetch-emails",
                trigger_type="timer",
                trigger_config={"interval_minutes": 20},
                isolation_level="shared",
                max_concurrent=1,
            ),
        ]

        runtime_config = AgentRuntimeConfig(
            webhook_host="127.0.0.1",
            webhook_port=8080,
            webhook_routes=[
                {
                    "source_id": "gmail",
                    "path": "/webhooks/gmail",
                    "methods": ["POST"],
                },
            ],
        )

        self._agent_runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
            config=runtime_config,
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

    async def run(
        self, context: dict, mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
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
default_agent = GmailInboxGuardianAgent()
