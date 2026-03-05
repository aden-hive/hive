"""Agent graph construction for Lead Qualification Agent."""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    enrichment_node,
    hot_lead_node,
    intake_node,
    nurture_node,
    output_node,
    review_node,
    routing_decision_node,
    scoring_node,
)

goal = Goal(
    id="lead-qualification-icp-scoring",
    name="Lead Qualification with ICP Scoring",
    description=(
        "Automatically score, enrich, and route inbound leads based on Ideal Customer "
        "Profile (ICP) criteria — eliminating manual triage and ensuring hot leads "
        "receive immediate attention."
    ),
    success_criteria=[
        SuccessCriterion(
            id="enrichment-completeness",
            description="Lead is enriched with firmographic data from web search",
            metric="enrichment_fields",
            target=">=4 fields",
            weight=0.20,
        ),
        SuccessCriterion(
            id="scoring-accuracy",
            description="Lead score is calculated with clear ICP-based breakdown",
            metric="score_breakdown_completeness",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="routing-correctness",
            description="Lead is routed to correct pipeline based on score",
            metric="routing_accuracy",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="crm-integration",
            description="Lead data is written to CRM with routing tags",
            metric="crm_update_success",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="execution-speed",
            description="Agent runs end-to-end in under 30 seconds per lead",
            metric="execution_time_seconds",
            target="<30",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="no-hallucination",
            description="Only include company data found through actual web search",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="human-checkpoint",
            description="Borderline leads (40-69 score) require human review before final routing",
            constraint_type="functional",
            category="interaction",
        ),
        Constraint(
            id="crm-write-back",
            description="All qualified leads must be written back to CRM with routing tags",
            constraint_type="functional",
            category="integration",
        ),
    ],
)

nodes = [
    intake_node,
    enrichment_node,
    scoring_node,
    routing_decision_node,
    hot_lead_node,
    review_node,
    nurture_node,
    output_node,
]

edges = [
    EdgeSpec(
        id="intake-to-enrichment",
        source="intake",
        target="enrichment",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="enrichment-to-scoring",
        source="enrichment",
        target="scoring",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="scoring-to-routing",
        source="scoring",
        target="routing_decision",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="routing-to-hot",
        source="routing_decision",
        target="hot_lead",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="route == 'hot'",
        priority=3,
    ),
    EdgeSpec(
        id="routing-to-review",
        source="routing_decision",
        target="review",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="route == 'review'",
        priority=2,
    ),
    EdgeSpec(
        id="routing-to-nurture",
        source="routing_decision",
        target="nurture",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="route == 'nurture'",
        priority=1,
    ),
    EdgeSpec(
        id="hot-to-output",
        source="hot_lead",
        target="output",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-to-hot",
        source="review",
        target="hot_lead",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="override_route == 'hot'",
        priority=2,
    ),
    EdgeSpec(
        id="review-to-nurture",
        source="review",
        target="nurture",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="override_route == 'nurture'",
        priority=1,
    ),
    EdgeSpec(
        id="nurture-to-output",
        source="nurture",
        target="output",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="output-to-intake",
        source="output",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="qualification_complete == 'true'",
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []


class LeadQualificationAgent:
    """
    Lead Qualification Agent — 8-node pipeline with human-in-the-loop review.

    Flow: intake -> enrichment -> scoring -> routing_decision
                                          ├─> hot_lead -> output
                                          ├─> review -> hot_lead/nurture -> output
                                          └─> nurture -> output

    Uses AgentRuntime for proper session management:
    - Session-scoped storage (sessions/{session_id}/)
    - Checkpointing for resume capability
    - Runtime logging
    - Data folder for save_data/load_data
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
            id="lead-qualification-agent-graph",
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
                "You are a lead qualification agent for a B2B SaaS company. "
                "You receive lead information, enrich it with company data from web search, "
                "score it against Ideal Customer Profile (ICP) criteria, and route it to the "
                "appropriate pipeline. You ensure hot leads get immediate attention while "
                "borderline cases receive human review. You never fabricate company data — "
                "only include information you actually found through web search."
            ),
        )

    def _setup(self, mock_mode=False) -> None:
        self._storage_path = (
            Path.home() / ".hive" / "agents" / "lead_qualification_agent"
        )
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
            "pause_nodes": self.pause_nodes,
            "terminal_nodes": self.terminal_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self):
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


default_agent = LeadQualificationAgent()
