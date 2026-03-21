"""Agent graph construction for Student Assignment Helper Agent."""

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
    research_node,
    outline_node,
    draft_node,
    review_node,
    report_node,
)

# Goal definition
goal = Goal(
    id="complete-student-assignment",
    name="Complete Student Assignment",
    description=(
        "Help a student complete a well-researched, properly structured, "
        "and academically written assignment on any topic — with checkpoints "
        "for outline approval and draft review."
    ),
    success_criteria=[
        SuccessCriterion(
            id="research-quality",
            description="At least 5 authoritative sources used for research",
            metric="source_count",
            target=">=5",
            weight=0.20,
        ),
        SuccessCriterion(
            id="outline-approval",
            description="Student approves the assignment outline before drafting",
            metric="outline_approved",
            target="true",
            weight=0.20,
        ),
        SuccessCriterion(
            id="word-limit-compliance",
            description="Final assignment is within 10% of the specified word limit",
            metric="word_count_compliance",
            target="true",
            weight=0.20,
        ),
        SuccessCriterion(
            id="citation-coverage",
            description="Every factual claim in the assignment cites its source",
            metric="citation_coverage",
            target="100%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="student-satisfaction",
            description="Student reviews and approves the draft before final delivery",
            metric="student_approval",
            target="true",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="no-plagiarism",
            description="All content must be paraphrased and properly cited — never copy-paste from sources",
            constraint_type="quality",
            category="academic-integrity",
        ),
        Constraint(
            id="no-hallucination",
            description="Only include information found in fetched sources",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="word-limit",
            description="Final assignment must stay within the student's specified word limit (±10%)",
            constraint_type="functional",
            category="requirements",
        ),
        Constraint(
            id="student-checkpoints",
            description="Student must approve outline and review draft before final delivery",
            constraint_type="functional",
            category="interaction",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    research_node,
    outline_node,
    draft_node,
    review_node,
    report_node,
]

# Edge definitions
edges = [
    # intake -> research
    EdgeSpec(
        id="intake-to-research",
        source="intake",
        target="research",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # research -> outline
    EdgeSpec(
        id="research-to-outline",
        source="research",
        target="outline",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # outline -> draft
    EdgeSpec(
        id="outline-to-draft",
        source="outline",
        target="draft",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # draft -> review
    EdgeSpec(
        id="draft-to-review",
        source="draft",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # review -> draft (revision loop)
    EdgeSpec(
        id="review-to-draft-revision",
        source="review",
        target="draft",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(needs_revision).lower() == 'true'",
        priority=2,
    ),
    # review -> report (student satisfied)
    EdgeSpec(
        id="review-to-report",
        source="review",
        target="report",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(needs_revision).lower() != 'true'",
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["report"]


class StudentAssignmentAgent:
    """
    Student Assignment Helper Agent — 6-node pipeline with student checkpoints.

    Flow: intake -> research -> outline -> draft -> review -> report
                                                      ^         |
                                                      +-- revision loop

    Features:
    - Gathers assignment requirements (topic, subject, word limit, level)
    - Researches topic from authoritative web sources
    - Creates structured outline with student approval
    - Writes a complete academic assignment draft
    - Reviews draft for quality, grammar, and citations
    - Delivers final polished assignment as HTML file

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
            id="student-assignment-agent-graph",
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
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "student_assignment_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

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
default_agent = StudentAssignmentAgent()
