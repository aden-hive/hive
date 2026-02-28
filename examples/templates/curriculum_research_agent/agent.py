"""Agent graph construction for Curriculum Research Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import AsyncEntryPointSpec, GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    intake_node,
    domain_research_node,
    standards_alignment_node,
    addie_synthesis_node,
    content_brief_node,
)

# Goal definition
goal = Goal(
    id="curriculum-research-agent",
    name="Curriculum Research Agent",
    description=(
        "Research current industry standards and best practices for a given "
        "topic, align findings to learning outcomes, and produce an ID-ready "
        "content brief structured around the ADDIE framework."
    ),
    success_criteria=[
        SuccessCriterion(
            id="source-quality",
            description=(
                "Research sources are from recognized professional bodies, "
                "government agencies, or peer-reviewed publications"
            ),
            metric="source_authority_rate",
            target=">=80%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="standards-alignment",
            description=(
                "Learning outcomes are mapped to accreditation competencies "
                "using appropriate Bloom's Taxonomy levels"
            ),
            metric="alignment_completeness",
            target=">=90%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="addie-completeness",
            description=(
                "Content brief includes all ADDIE components: needs analysis, "
                "module structure, objectives, assessments, and resources"
            ),
            metric="addie_coverage",
            target="100%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="brief-actionability",
            description=(
                "Content brief is directly usable by an instructional designer "
                "without requiring additional research"
            ),
            metric="actionability_score",
            target=">=85%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="authoritative-sources-only",
            description=(
                "Only use sources from recognized professional bodies, "
                "government agencies, accreditation authorities, or "
                "peer-reviewed publications. Exclude marketing content."
            ),
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="blooms-taxonomy-alignment",
            description=(
                "All learning objectives must use Bloom's Taxonomy verbs "
                "appropriate to the specified education level"
            ),
            constraint_type="hard",
            category="pedagogical",
        ),
        Constraint(
            id="accreditation-compliance",
            description=(
                "Content brief must address all competencies required by "
                "the specified accreditation context"
            ),
            constraint_type="hard",
            category="compliance",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    domain_research_node,
    standards_alignment_node,
    addie_synthesis_node,
    content_brief_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-research",
        source="intake",
        target="domain-research",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="research-to-alignment",
        source="domain-research",
        target="standards-alignment",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="alignment-to-addie",
        source="standards-alignment",
        target="addie-synthesis",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="addie-to-brief",
        source="addie-synthesis",
        target="content-brief",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="brief-to-intake",
        source="content-brief",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
async_entry_points: list[AsyncEntryPointSpec] = []
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
    "You are a Curriculum Research assistant specializing in instructional "
    "design. You help educators and L&D professionals develop structured "
    "content briefs by researching current industry standards, aligning "
    "findings to learning outcomes, and applying the ADDIE framework."
)


class CurriculumResearchAgent:
    """
    Curriculum Research Agent — 5-node pipeline for content brief generation.

    Flow: intake -> domain-research -> standards-alignment -> addie-synthesis
          -> content-brief -> intake (loop)

    Pipeline:
    1. intake: Receive topic, audience, level, and accreditation context
    2. domain-research: Tavily search for current standards and best practices
    3. standards-alignment: Map findings to learning outcomes and competencies
    4. addie-synthesis: Apply ADDIE framework to structure curriculum
    5. content-brief: Present ID-ready brief to user
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
        self._agent_runtime: AgentRuntime | None = None
        self._graph: GraphSpec | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="curriculum-research-agent-graph",
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
        self._storage_path = (
            Path.home() / ".hive" / "agents" / "curriculum_research_agent"
        )
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        tools_path = Path(__file__).parent / "tools.py"
        if tools_path.exists():
            self._tool_registry.discover_from_module(tools_path)

        if mock_mode:
            from framework.llm.mock import MockLLMProvider
            llm = MockLLMProvider()
        else:
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
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")

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
default_agent = CurriculumResearchAgent()
