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
    intake_node,
    job_search_node,
    job_review_node,
    customize_node,
)

# Goal definition
goal = Goal(
    id="job-hunter",
    name="Job Hunter",
    description=(
        "Analyze a user's resume to identify their strongest role fits, find 10 "
        "matching job opportunities, let the user select which to pursue, then "
        "generate a resume customization list and cold outreach email for each selected job."
    ),
    success_criteria=[
        SuccessCriterion(
            id="role-identification",
            description="Identifies 2-3 role types that genuinely match the user's experience",
            metric="role_match_accuracy",
            target=">=0.8",
            weight=0.2,
        ),
        SuccessCriterion(
            id="job-relevance",
            description="Found jobs align with identified roles and user's background",
            metric="job_relevance_score",
            target=">=0.8",
            weight=0.2,
        ),
        SuccessCriterion(
            id="customization-quality",
            description="Resume changes are specific, actionable, and tailored to each job posting",
            metric="customization_specificity",
            target=">=0.85",
            weight=0.25,
        ),
        SuccessCriterion(
            id="email-effectiveness",
            description="Cold emails are personalized, professional, and reference specific company/role details",
            metric="email_personalization_score",
            target=">=0.85",
            weight=0.2,
        ),
        SuccessCriterion(
            id="user-satisfaction",
            description="User approves outputs without major revisions needed",
            metric="approval_rate",
            target=">=0.9",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="realistic-roles",
            description="Only suggest roles the user is realistically qualified for - no aspirational stretch roles",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="truthful-customizations",
            description="Resume customizations must be truthful - enhance presentation, never fabricate experience",
            constraint_type="ethical",
            category="integrity",
        ),
        Constraint(
            id="professional-emails",
            description="Cold emails must be professional and not spammy",
            constraint_type="quality",
            category="tone",
        ),
        Constraint(
            id="respect-selection",
            description="Only customize for jobs the user explicitly selects",
            constraint_type="behavioral",
            category="user_control",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    job_search_node,
    job_review_node,
    customize_node,
]

# Edge definitions
edges = [
    # intake -> job-search
    EdgeSpec(
        id="intake-to-job-search",
        source="intake",
        target="job-search",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # job-search -> job-review
    EdgeSpec(
        id="job-search-to-job-review",
        source="job-search",
        target="job-review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # job-review -> customize
    EdgeSpec(
        id="job-review-to-customize",
        source="job-review",
        target="customize",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["customize"]


class JobHunterAgent:
    """
    Job Hunter Agent — 4-node pipeline for job search and application materials.

    Flow: intake -> job-search -> job-review -> customize

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
                "max_tool_calls_per_turn": 30,
                "max_history_tokens": 32000,
            },
            conversation_mode="continuous",
            identity_prompt=(
                "You are a job hunting assistant. You analyze resumes to identify "
                "the strongest role fits, search for matching job opportunities, "
                "and help create personalized application materials. You only "
                "suggest roles the user is realistically qualified for, and you "
                "never fabricate experience — only enhance presentation truthfully."
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
