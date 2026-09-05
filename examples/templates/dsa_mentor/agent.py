"""DSA Mentor Agent — goal, edges, graph spec, and agent class."""

import sys
from pathlib import Path

# Ensure core and tools directories are in path for framework imports
# This is needed when running as a module from examples/templates/
_agent_file = Path(__file__).resolve()
_project_root = _agent_file.parent.parent.parent.parent
_core_dir = _project_root / "core"
_tools_src_dir = _project_root / "tools" / "src"
if str(_core_dir) not in sys.path:
    sys.path.insert(0, str(_core_dir))
if str(_tools_src_dir) not in sys.path:
    sys.path.insert(0, str(_tools_src_dir))

from framework.graph import EdgeCondition, EdgeSpec, Goal, SuccessCriterion, Constraint  # noqa: E402
from framework.graph.edge import GraphSpec  # noqa: E402
from framework.graph.executor import GraphExecutor  # noqa: E402
from framework.runtime.core import Runtime  # noqa: E402
from framework.llm.anthropic import AnthropicProvider  # noqa: E402

from .config import default_config, RuntimeConfig  # noqa: E402
from .nodes import all_nodes  # noqa: E402

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
# Edges
# ---------------------------------------------------------------------------
edges = [
    # Main flow: intake -> analyze -> hint
    EdgeSpec(
        id="intake-to-analyze",
        source="intake",
        target="analyze-problem",
        condition=EdgeCondition.ON_SUCCESS,
        description="After collecting problem statement, analyze the problem",
    ),
    EdgeSpec(
        id="analyze-to-hint",
        source="analyze-problem",
        target="provide-hint",
        condition=EdgeCondition.ON_SUCCESS,
        description="After analyzing problem, provide hints",
    ),
    # Conditional: if code provided, review it
    EdgeSpec(
        id="hint-to-review",
        source="provide-hint",
        target="review-code",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="user_code and user_code != ''",
        priority=10,
        description="If user provided code, review it",
    ),
    # After code review, identify weaknesses
    EdgeSpec(
        id="review-to-weaknesses",
        source="review-code",
        target="identify-weaknesses",
        condition=EdgeCondition.ON_SUCCESS,
        description="After code review, identify weak areas",
    ),
    # If no code review, go directly to weaknesses from hint
    EdgeSpec(
        id="hint-to-weaknesses",
        source="provide-hint",
        target="identify-weaknesses",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="not user_code or user_code == ''",
        priority=5,
        description="If no code provided, identify weaknesses from problem analysis",
    ),
    # Finally, suggest practice plan
    EdgeSpec(
        id="weaknesses-to-practice",
        source="identify-weaknesses",
        target="suggest-practice",
        condition=EdgeCondition.ON_SUCCESS,
        description="After identifying weaknesses, suggest practice plan",
    ),
    # Allow hint escalation (user asks for more specific hint)
    EdgeSpec(
        id="hint-escalation",
        source="provide-hint",
        target="provide-hint",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="hint_level and hint_level < 4",
        priority=1,
        description="Allow hint level escalation if user needs more help",
    ),
]

# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------
entry_node = "intake"
entry_points = {"start": "intake"}
terminal_nodes = ["suggest-practice"]
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
