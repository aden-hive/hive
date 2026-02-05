"""Marketing Content Agent — goal, edges, graph spec, and agent class."""

from pathlib import Path

from framework.graph import EdgeCondition, EdgeSpec, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime
from framework.llm.anthropic import AnthropicProvider

from .config import default_config, RuntimeConfig
from .nodes import all_nodes

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------
goal = Goal(
    id="marketing-content",
    name="Marketing Content Generator",
    description=(
        "Generate targeted marketing content across multiple channels "
        "for a given product and audience."
    ),
    success_criteria=[
        SuccessCriterion(
            id="audience-analyzed",
            description="Audience analysis is produced with demographics and pain points",
            metric="output_contains",
            target="audience_analysis",
        ),
        SuccessCriterion(
            id="content-generated",
            description="At least 2 channel-specific content pieces are generated",
            metric="custom",
            target="len(content) >= 2",
        ),
        SuccessCriterion(
            id="variants-provided",
            description="A/B variants are provided for each content piece",
            metric="custom",
            target="all variants present",
        ),
    ],
    constraints=[
        Constraint(
            id="no-competitor-names",
            description="No competitor brand names in generated content",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="social-length",
            description="Social media content should be under 280 characters",
            constraint_type="soft",
            category="quality",
        ),
    ],
    input_schema={
        "product_description": {"type": "string"},
        "target_audience": {"type": "string"},
        "brand_voice": {"type": "string"},
        "channels": {"type": "array", "items": {"type": "string"}},
    },
    output_schema={
        "audience_analysis": {"type": "object"},
        "content": {"type": "array"},
    },
)

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
edges = [
    EdgeSpec(
        id="analyze-to-generate",
        source="analyze-audience",
        target="generate-content",
        condition=EdgeCondition.ON_SUCCESS,
        description="After audience analysis, generate content",
    ),
    EdgeSpec(
        id="generate-to-review",
        source="generate-content",
        target="review-and-refine",
        condition=EdgeCondition.ON_SUCCESS,
        description="After content generation, review and refine",
    ),
    EdgeSpec(
        id="review-to-regenerate",
        source="review-and-refine",
        target="generate-content",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="needs_revision == True",
        priority=10,
        description="If revision needed, loop back to content generation",
    ),
]

# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------
entry_node = "analyze-audience"
entry_points = {"start": "analyze-audience"}
terminal_nodes = ["review-and-refine"]
pause_nodes = []
nodes = all_nodes


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class MarketingAgent:
    """Multi-channel marketing content generator agent."""

    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.terminal_nodes = terminal_nodes
        self.executor = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="marketing-content-graph",
            goal_id=self.goal.id,
            entry_node=self.entry_node,
            entry_points=entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            description="Marketing content generation workflow",
        )

    def _create_executor(self):
        runtime = Runtime(storage_path=Path(self.config.storage_path).expanduser())
        llm = AnthropicProvider(model=self.config.model)
        self.executor = GraphExecutor(runtime=runtime, llm=llm)
        return self.executor

    async def run(self, context: dict, mock_mode: bool = False) -> dict:
        graph = self._build_graph()
        executor = self._create_executor()
        result = await executor.execute(
            graph=graph,
            goal=self.goal,
            input_data=context,
        )
        return {
            "success": result.success,
            "output": result.output,
            "steps": result.steps_executed,
            "path": result.path,
        }


default_agent = MarketingAgent()
