"""Agent graph construction for SDR Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import AsyncEntryPointSpec, GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    intake_node,
    score_contacts_node,
    filter_contacts_node,
    personalize_node,
    send_outreach_node,
    report_node,
)

# Goal definition
goal = Goal(
    id="sdr-agent",
    name="SDR Agent",
    description=(
        "Automate sales development outreach: score contacts by priority, "
        "filter suspicious profiles, generate personalized messages, "
        "and create Gmail drafts for human review."
    ),
    success_criteria=[
        SuccessCriterion(
            id="contact-scoring-accuracy",
            description=(
                "Contacts are correctly scored and ranked by priority factors "
                "(alumni status, connection degree, domain verification)"
            ),
            metric="scoring_accuracy",
            target=">=90%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="scam-filter-effectiveness",
            description=(
                "Suspicious profiles (risk_score >= 7) are correctly identified "
                "and excluded from outreach"
            ),
            metric="filter_precision",
            target=">=95%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="message-personalization",
            description=(
                "Generated messages reference specific profile details "
                "(alumni connection, role, company) and match the outreach goal"
            ),
            metric="personalization_score",
            target=">=80%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="draft-creation",
            description="Gmail drafts are created for all safe contacts without errors",
            metric="draft_success_rate",
            target="100%",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="draft-not-send",
            description="Agent creates Gmail drafts but NEVER sends emails automatically",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="respect-batch-limit",
            description="Must not process more contacts than the configured max_contacts parameter",
            constraint_type="hard",
            category="operational",
        ),
        Constraint(
            id="skip-suspicious",
            description="Contacts with risk_score >= 7 must be excluded from outreach",
            constraint_type="hard",
            category="safety",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    score_contacts_node,
    filter_contacts_node,
    personalize_node,
    send_outreach_node,
    report_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-score",
        source="intake",
        target="score-contacts",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="score-to-filter",
        source="score-contacts",
        target="filter-contacts",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="filter-to-personalize",
        source="filter-contacts",
        target="personalize",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="personalize-to-send",
        source="personalize",
        target="send-outreach",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="send-to-report",
        source="send-outreach",
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
async_entry_points: list[AsyncEntryPointSpec] = []  # SDR Agent is manually triggered
pause_nodes = []
terminal_nodes = []
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_tool_result_chars": 8000,
    "max_history_tokens": 32000,
}
conversation_mode = "continuous"
identity_prompt = (
    "You are an SDR (Sales Development Representative) assistant. "
    "You help users automate their outreach by scoring contacts, filtering "
    "suspicious profiles, generating personalized messages, and creating "
    "Gmail drafts — all with human review before anything is sent."
)


class SDRAgent:
    """
    SDR Agent — 6-node pipeline for automated outreach.

    Flow: intake -> score-contacts -> filter-contacts -> personalize
          -> send-outreach -> report -> intake (loop)

    Pipeline:
    1. intake: Receive contact list and outreach goal
    2. score-contacts: Rank contacts 0-100 by priority factors
    3. filter-contacts: Remove suspicious profiles (risk >= 7)
    4. personalize: Generate personalized messages for each contact
    5. send-outreach: Create Gmail drafts (never sends automatically)
    6. report: Summarize campaign results and present to user
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
        self._executor: None = None
        self._graph: GraphSpec | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="sdr-agent-graph",
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

    def _setup(self, mock_mode=False) -> None:
        """Set up the agent runtime with sessions, checkpoints, and logging."""
        self._storage_path = Path.home() / ".hive" / "agents" / "sdr_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

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
        )

        return self._executor

    async def start(self, mock_mode=False) -> None:
        """Set up the agent (initialize executor and tools)."""
        if self._executor is None:
            self._setup(mock_mode=mock_mode)

    async def stop(self) -> None:
        """Stop and clean up the agent runtime."""
        if self._agent_runtime is not None and self._agent_runtime.is_running:
            await self._agent_runtime.stop()

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

        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data,
            timeout=timeout,
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
default_agent = SDRAgent()
