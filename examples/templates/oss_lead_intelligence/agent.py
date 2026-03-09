"""
OSS Lead Intelligence Agent - Main Agent Definition.

Transforms GitHub repository interest signals into qualified CRM contacts
with enrichment data and team notifications.

Features:
- Multi-tool CRM integration (GitHub + Apollo + HubSpot + Slack)
- Human-in-the-loop lead review
- Configurable ICP scoring
- Optional email outreach
"""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config
from .nodes import (
    config_intake_node,
    crm_sync_and_notify_node,
    enrich_and_score_node,
    github_scan_node,
    review_leads_node,
)

goal = Goal(
    id="oss-lead-intelligence",
    name="Open-Source Lead Intelligence",
    description=(
        "Transform GitHub repository interest signals (stars, forks, contributions) "
        "into qualified CRM contacts with enrichment data and team notifications."
    ),
    success_criteria=[
        SuccessCriterion(
            id="signal-capture",
            description="Successfully scan stargazers from specified repositories",
            metric="profiles_scanned",
            target=">0",
            weight=0.15,
        ),
        SuccessCriterion(
            id="intelligent-filtering",
            description="Filter out bots and low-signal profiles with high precision",
            metric="filter_accuracy",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="enrichment-coverage",
            description="Attempt Apollo enrichment for all filtered profiles",
            metric="enrichment_attempted",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="scoring-accuracy",
            description="Score leads against ICP criteria with reproducible logic",
            metric="leads_scored",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="human-approval",
            description="Present leads for human review before any CRM action",
            metric="review_completed",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="crm-sync",
            description="Create contacts and companies in HubSpot with enrichment data",
            metric="crm_records_created",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="team-notification",
            description="Post campaign summary to Slack with actionable metrics",
            metric="notification_sent",
            target="true",
            weight=0.10,
        ),
    ],
    constraints=[
        Constraint(
            id="public-data-only",
            description="Only process data from public GitHub API and Apollo enrichment",
            constraint_type="hard",
            category="privacy",
        ),
        Constraint(
            id="no-auto-email",
            description="Email outreach disabled by default, requires explicit opt-in",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="no-crm-deletion",
            description="Only create/update CRM records, never delete",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="rate-limit-respect",
            description="Respect GitHub and Apollo API rate limits",
            constraint_type="hard",
            category="operational",
        ),
    ],
)

nodes = [
    config_intake_node,
    github_scan_node,
    enrich_and_score_node,
    review_leads_node,
    crm_sync_and_notify_node,
]

edges = [
    EdgeSpec(
        id="config-to-github-scan",
        source="config-intake",
        target="github-scan",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="github-scan-to-enrich",
        source="github-scan",
        target="enrich-and-score",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="enrich-to-review",
        source="enrich-and-score",
        target="review-leads",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="len(high_score_leads) > 0",
        priority=1,
    ),
    EdgeSpec(
        id="review-to-crm",
        source="review-leads",
        target="crm-sync-and-notify",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="len(approved_leads) > 0",
        priority=1,
    ),
]

entry_node = "config-intake"
entry_points = {
    "start": "config-intake",
    "resume_from_review": "review-leads",
}
pause_nodes = []
terminal_nodes = ["crm-sync-and-notify", "review-leads", "enrich-and-score"]

conversation_mode = "continuous"
identity_prompt = """You are the OSS Lead Intelligence Agent, a specialized agent that helps developer tools companies identify high-value leads from their GitHub repository activity.

Your mission is to:
1. Scan GitHub repositories for stargazers and contributors
2. Filter out bots and low-quality profiles
3. Enrich profiles with business data from Apollo
4. Score leads against the customer's Ideal Customer Profile (ICP)
5. Present qualified leads for human review
6. Sync approved leads to HubSpot CRM
7. Notify the team via Slack

You are professional, data-driven, and respectful of privacy. You only use publicly available data and always require human approval before taking CRM actions.

You communicate clearly about lead quality, scoring rationale, and campaign progress."""

loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 20,
    "max_history_tokens": 32000,
}


class OSSLeadIntelligenceAgent:
    """
    OSS Lead Intelligence Agent.

    A 5-node pipeline for transforming GitHub signals into qualified CRM contacts.
    Demonstrates: multi-tool integration, HITL review, conditional routing,
    and CRM synchronization.
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
        return GraphSpec(
            id="oss-lead-intelligence-graph",
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
        self._storage_path = Path.home() / ".hive" / "agents" / "oss_lead_intelligence"
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

    async def start(self, mock_mode=False) -> None:
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
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
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def validate(self):
        errors = []
        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        return {"valid": len(errors) == 0, "errors": errors}


default_agent = OSSLeadIntelligenceAgent()
