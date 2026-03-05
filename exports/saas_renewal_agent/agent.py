"""Agent graph construction for SaaS Renewal & Upsell Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    intake_node,
    data_load_node,
    classify_node,
    playbook_node,
    draft_node,
    review_node,
    send_log_node,
    digest_node,
)

goal = Goal(
    id="saas-renewal-upsell",
    name="SaaS Renewal & Upsell Agent",
    description=(
        "Monitor SaaS subscription data for upcoming renewals, usage drop signals, "
        "and expansion opportunities. Generate personalized renewal and upsell outreach "
        "drafted for account manager review and approval to maximize Net Revenue Retention."
    ),
    success_criteria=[
        SuccessCriterion(
            id="data-loaded",
            description="Successfully loaded and validated subscription and usage data",
            metric="data_validation",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="accounts-classified",
            description="All accounts classified into Renewal Risk, Expansion Ready, or Healthy",
            metric="classification_coverage",
            target="100%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="drafts-generated",
            description="Personalized email drafts generated for actionable accounts",
            metric="draft_count",
            target=">=1",
            weight=0.20,
        ),
        SuccessCriterion(
            id="user-approval",
            description="User reviews and approves outreach drafts before sending",
            metric="user_approval",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="nrr-report-generated",
            description="Comprehensive NRR digest report generated with recommendations",
            metric="report_created",
            target="true",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="human-approval-required",
            description="No outreach message can be sent without explicit human approval",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="data-privacy",
            description="Subscription and usage data must be handled securely and not exposed in logs",
            constraint_type="hard",
            category="privacy",
        ),
        Constraint(
            id="accurate-classification",
            description="Account classifications must be based on actual data, not assumptions",
            constraint_type="hard",
            category="accuracy",
        ),
        Constraint(
            id="personalized-outreach",
            description="Each email draft must include account-specific personalization",
            constraint_type="soft",
            category="quality",
        ),
    ],
)

nodes = [
    intake_node,
    data_load_node,
    classify_node,
    playbook_node,
    draft_node,
    review_node,
    send_log_node,
    digest_node,
]

edges = [
    EdgeSpec(
        id="intake-to-data_load",
        source="intake",
        target="data_load",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="data_load-to-classify",
        source="data_load",
        target="classify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-playbook",
        source="classify",
        target="playbook",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="playbook-to-draft",
        source="playbook",
        target="draft",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="draft-to-review",
        source="draft",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-to-send_log",
        source="review",
        target="send_log",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved_drafts is not None",
        priority=2,
    ),
    EdgeSpec(
        id="review-to-classify-feedback",
        source="review",
        target="classify",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="feedback is not None",
        priority=1,
    ),
    EdgeSpec(
        id="send_log-to-digest",
        source="send_log",
        target="digest",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="digest-to-intake",
        source="digest",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(next_action).lower() == 'new_data'",
        priority=1,
    ),
    EdgeSpec(
        id="digest-to-classify",
        source="digest",
        target="classify",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(next_action).lower() in ['detailed_analysis', 'adjust_thresholds']",
        priority=2,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []

conversation_mode = "continuous"
identity_prompt = (
    "You are the SaaS Renewal & Upsell Agent, a revenue expansion specialist. "
    "You analyze subscription data, classify accounts by opportunity type, "
    "draft personalized outreach for account manager review, and generate "
    "NRR reports. You are proactive, data-driven, and always require human "
    "approval before any outreach is sent. You help SaaS companies maximize "
    "Net Revenue Retention through intelligent, personalized engagement."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 64000,
}


class SaaSRenewalAgent:
    """
    SaaS Renewal & Upsell Agent - Proactive Revenue Expansion.

    Flow: intake -> data_load -> classify -> playbook -> draft -> review -> send_log -> digest

    Features:
    - Subscription and usage data analysis
    - Account classification (Renewal Risk, Expansion Ready, Healthy)
    - Personalized email drafting
    - Human-in-the-loop approval
    - NRR digest reporting
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
            id="saas-renewal-agent-graph",
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

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the agent runtime with sessions, checkpoints, and logging."""
        self._storage_path = Path.home() / ".hive" / "agents" / "saas_renewal_agent"
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
            )
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

    async def start(self, mock_mode: bool = False) -> None:
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
        self, context: dict, mock_mode: bool = False, session_state: dict | None = None
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


default_agent = SaaSRenewalAgent()
