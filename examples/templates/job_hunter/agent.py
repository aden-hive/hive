"""Agent graph construction for Job Hunter Agent."""

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
    resume_uploader_node,
    resume_parser_node,
    preference_intake_node,
    market_analyst_node,
    job_selector_node,
    jd_parser_node,
    ats_analyzer_node,
    chief_strategist_node,
    senior_copywriter_node,
    critic_node,
    revision_router_node,
    publisher_node,
)

# Goal definition
goal = Goal(
    id="job-hunter",
    name="Job Hunter",
    description=(
        "Parse and ATS-score a user's resume, research live market demand, find 10 matching "
        "job opportunities, let the user select which to pursue, then generate ATS-optimized "
        "resume customizations and cold outreach emails for each selected job."
    ),
    success_criteria=[
        SuccessCriterion(
            id="resume-parsing-accuracy",
            description="Resume is fully parsed with all sections, skills, and errors identified",
            metric="parse_completeness",
            target=">=0.95",
            weight=0.1,
        ),
        SuccessCriterion(
            id="ats-scoring-accuracy",
            description="ATS scores accurately reflect keyword match rate and format quality",
            metric="ats_score_validity",
            target=">=0.85",
            weight=0.15,
        ),
        SuccessCriterion(
            id="role-identification",
            description="Identifies 3-5 role types that genuinely match the user's actual experience",
            metric="role_match_accuracy",
            target=">=0.8",
            weight=0.15,
        ),
        SuccessCriterion(
            id="job-relevance",
            description="Found jobs align with identified roles and user's background",
            metric="job_relevance_score",
            target=">=0.8",
            weight=0.15,
        ),
        SuccessCriterion(
            id="customization-quality",
            description="Resume changes are specific, actionable, and tailored to each job posting",
            metric="customization_specificity",
            target=">=0.85",
            weight=0.2,
        ),
        SuccessCriterion(
            id="email-effectiveness",
            description="Cold emails are personalized, professional, and reference specific company details",
            metric="email_personalization_score",
            target=">=0.85",
            weight=0.15,
        ),
        SuccessCriterion(
            id="user-satisfaction",
            description="User approves outputs without major revisions needed",
            metric="approval_rate",
            target=">=0.9",
            weight=0.1,
        ),
    ],
    constraints=[
        Constraint(
            id="realistic-roles",
            description="Only suggest roles the user is realistically qualified for — no aspirational stretch roles",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="truthful-customizations",
            description="Resume customizations must be truthful — enhance presentation, never fabricate experience",
            constraint_type="ethical",
            category="integrity",
        ),
        Constraint(
            id="professional-emails",
            description="Cold emails must be professional, specific, and not spammy",
            constraint_type="quality",
            category="tone",
        ),
        Constraint(
            id="respect-selection",
            description="Only generate materials for jobs the user explicitly selects",
            constraint_type="behavioral",
            category="user_control",
        ),
        Constraint(
            id="no-fabrication",
            description="Keyword injections and bullet rewrites must never introduce experience the candidate does not have",
            constraint_type="ethical",
            category="integrity",
        ),
    ],
)

# Node list
nodes = [
    resume_uploader_node,
    resume_parser_node,
    preference_intake_node,
    market_analyst_node,
    job_selector_node,
    jd_parser_node,
    ats_analyzer_node,
    chief_strategist_node,
    senior_copywriter_node,
    critic_node,
    revision_router_node,
    publisher_node,
]

# Edge definitions
edges = [
    # resume_uploader -> resume_parser
    EdgeSpec(
        id="resume-uploader-to-resume-parser",
        source="resume_uploader",
        target="resume_parser",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # resume_parser -> preference_intake
    EdgeSpec(
        id="resume-parser-to-preference-intake",
        source="resume_parser",
        target="preference_intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # preference_intake -> market_analyst
    EdgeSpec(
        id="preference-intake-to-market-analyst",
        source="preference_intake",
        target="market_analyst",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # market_analyst -> job_selector
    EdgeSpec(
        id="market-analyst-to-job-selector",
        source="market_analyst",
        target="job_selector",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # job_selector -> jd_parser
    EdgeSpec(
        id="job-selector-to-jd-parser",
        source="job_selector",
        target="jd_parser",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # jd_parser -> ats_analyzer
    EdgeSpec(
        id="jd-parser-to-ats-analyzer",
        source="jd_parser",
        target="ats_analyzer",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # ats_analyzer -> chief_strategist
    EdgeSpec(
        id="ats-analyzer-to-chief-strategist",
        source="ats_analyzer",
        target="chief_strategist",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # chief_strategist -> senior_copywriter
    EdgeSpec(
        id="chief-strategist-to-senior-copywriter",
        source="chief_strategist",
        target="senior_copywriter",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # senior_copywriter -> critic
    EdgeSpec(
        id="senior-copywriter-to-critic",
        source="senior_copywriter",
        target="critic",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # critic -> revision_router
    EdgeSpec(
        id="critic-to-revision-router",
        source="critic",
        target="revision_router",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # revision_router -> publisher
    EdgeSpec(
        id="revision-router-to-publisher",
        source="revision_router",
        target="publisher",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "resume_uploader"
entry_points = {"start": "resume_uploader"}
pause_nodes = []
terminal_nodes = ["publisher"]


class JobHunterAgent:
    """
    Job Hunter Agent — 12-node pipeline for resume analysis, job search, and application materials.

    Flow:
      resume_uploader -> resume_parser -> preference_intake -> market_analyst
      -> job_selector -> jd_parser -> ats_analyzer -> chief_strategist
      -> senior_copywriter -> critic -> revision_router -> publisher

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
        """Build the GraphSpec."""
        return GraphSpec(
            id="job-hunter-graph",
            goal_id=self.goal.id,
            version="2.0.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            loop_config={
                "max_iterations": 200,
                "max_tool_calls_per_turn": 20,
                "max_history_tokens": 32000,
            },
            conversation_mode="continuous",
            identity_prompt=(
                "You are a job hunting assistant. You parse resumes, score them for ATS "
                "compatibility, research live market demand, find matching jobs, and produce "
                "tailored application materials. You only suggest roles the user is realistically "
                "qualified for, and you never fabricate experience — only enhance presentation truthfully."
            ),
        )

    def _setup(self, mock_mode=False) -> None:
        """Set up the agent runtime with sessions, checkpoints, and logging."""
        self._storage_path = Path.home() / ".hive" / "agents" / "job_hunter"
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
default_agent = JobHunterAgent()
