"""Agent graph construction for Meeting Notes & Action Item Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    validate_input_node,
    extract_meeting_data_node,
    parse_and_validate_node,
    format_slack_node,
    post_to_slack_node,
    compile_output_node,
    handle_error_node,
    validate_input,
    extract_meeting_data,
    parse_and_validate_output,
    format_slack_message,
    post_to_slack,
    compile_final_output,
    handle_error,
)

# Goal definition
goal = Goal(
    id="meeting-notes-agent",
    name="Meeting Notes & Action Item Agent",
    description=(
        "Given a meeting transcript, produce a fully structured report containing: "
        "an executive summary, list of key decisions, action items with assigned owners "
        "and due dates, blockers flagged during the meeting, and follow-up items. "
        "Optionally deliver the report to a Slack channel."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-summary",
            description="A concise 2-3 sentence executive summary is produced",
            metric="summary_produced",
            target="true",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-action-items",
            description="All action items extracted with owner, due date, and priority",
            metric="action_items_count",
            target=">=1",
            weight=0.3,
        ),
        SuccessCriterion(
            id="sc-decisions",
            description="All key decisions agreed upon are captured",
            metric="decisions_captured",
            target="true",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-output-format",
            description="Output is valid JSON matching the MeetingNotesOutput schema",
            metric="schema_valid",
            target="true",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-slack-delivery",
            description="When a Slack channel is specified, report is delivered successfully",
            metric="slack_message_sent",
            target="true",
            weight=0.1,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-hallucination",
            description="Only extract information explicitly stated in the transcript; never fabricate names, dates, or tasks",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-owner-assignment",
            description="Action items must only be assigned to people explicitly named in the transcript",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-dual-llm",
            description="Agent supports both Anthropic Claude and Google Gemini selectable at runtime",
            constraint_type="soft",
            category="flexibility",
        ),
    ],
)

# Node list
nodes = [
    validate_input_node,
    extract_meeting_data_node,
    parse_and_validate_node,
    format_slack_node,
    post_to_slack_node,
    compile_output_node,
    handle_error_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="validate-to-extract",
        source="validate-input",
        target="extract-meeting-data",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="validate-to-error",
        source="validate-input",
        target="handle-error",
        condition=EdgeCondition.ON_FAILURE,
        priority=1,
    ),
    EdgeSpec(
        id="extract-to-parse",
        source="extract-meeting-data",
        target="parse-and-validate",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="extract-to-error",
        source="extract-meeting-data",
        target="handle-error",
        condition=EdgeCondition.ON_FAILURE,
        priority=1,
    ),
    EdgeSpec(
        id="parse-to-slack-format",
        source="parse-and-validate",
        target="format-slack-message",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="parse-to-error",
        source="parse-and-validate",
        target="handle-error",
        condition=EdgeCondition.ON_FAILURE,
        priority=1,
    ),
    EdgeSpec(
        id="slack-format-to-post",
        source="format-slack-message",
        target="post-to-slack",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="post-slack-to-compile",
        source="post-to-slack",
        target="compile-final-output",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "validate-input"
entry_points = {"start": "validate-input"}
pause_nodes = []
terminal_nodes = ["compile-final-output", "handle-error"]


class MeetingNotesAgent:
    """
    Meeting Notes & Action Item Agent — 7-node pipeline.

    Flow:
        validate-input
            ├─ ON_SUCCESS → extract-meeting-data → parse-and-validate
            │                                           ├─ ON_SUCCESS → format-slack-message → post-to-slack → compile-final-output
            │                                           └─ ON_FAILURE → handle-error
            └─ ON_FAILURE → handle-error
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
            id="meeting-notes-agent-graph",
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
                "max_iterations": 20,
                "max_tool_calls_per_turn": 5,
                "max_history_tokens": 16000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "meeting_notes_agent"
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
            if edge.target is not None and edge.target not in node_ids:
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
default_agent = MeetingNotesAgent()

# ── Module-level exports for AgentRunner ─────────────────────────────────────
__all__ = [
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "MeetingNotesAgent",
    "default_agent",
]
