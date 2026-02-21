"""DSA Mentor Agent — goal, edges, graph spec, and agent class."""

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
    id="dsa-mentor",
    name="DSA Mentor Agent",
    description=(
        "Act as an AI coding mentor that provides guided hints, reviews code quality, "
        "identifies weak DSA areas, and suggests personalized practice plans for algorithm learning."
    ),
    success_criteria=[
        SuccessCriterion(
            id="hint-quality",
            description="Provides progressive hints without revealing full solutions",
            metric="llm_judge",
            target="Hints are helpful but not complete solutions",
            weight=0.3,
        ),
        SuccessCriterion(
            id="code-review",
            description="Reviews code for correctness, complexity, and optimization opportunities",
            metric="output_contains",
            target="code_review",
            weight=0.25,
        ),
        SuccessCriterion(
            id="weakness-identification",
            description="Identifies specific weak areas (e.g., DP, graphs, greedy algorithms)",
            metric="output_contains",
            target="weak_areas",
            weight=0.2,
        ),
        SuccessCriterion(
            id="personalized-plan",
            description="Suggests targeted practice problems based on identified weaknesses",
            metric="output_contains",
            target="practice_plan",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="no-direct-solutions",
            description="Never provide complete solutions - only hints and guidance",
            constraint_type="hard",
            category="educational",
        ),
        Constraint(
            id="progressive-hints",
            description="Hints should be progressive - start vague, get more specific if needed",
            constraint_type="soft",
            category="quality",
        ),
    ],
    input_schema={
        "problem_statement": {"type": "string"},
        "user_code": {"type": "string", "optional": True},
        "user_question": {"type": "string", "optional": True},
        "difficulty_level": {"type": "string", "optional": True},
    },
    output_schema={
        "hint": {"type": "string"},
        "code_review": {"type": "object", "optional": True},
        "weak_areas": {"type": "array", "optional": True},
        "practice_plan": {"type": "array", "optional": True},
    },
)

# ---------------------------------------------------------------------------
# Edges (will add as we build nodes)
# ---------------------------------------------------------------------------
edges = []

# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------
entry_node = "intake"
entry_points = {"start": "intake"}
terminal_nodes = ["intake"]  # Temporary - will update as we add more nodes
pause_nodes = []


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class DSAMentorAgent:
    """DSA Mentor Agent for algorithm learning."""

    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = all_nodes
        self.edges = edges
        self.entry_node = entry_node
        self.terminal_nodes = terminal_nodes
        self.executor = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="dsa-mentor-graph",
            goal_id=self.goal.id,
            entry_node=self.entry_node,
            entry_points=entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            description="DSA Mentor Agent workflow",
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


default_agent = DSAMentorAgent()
