"""Coding Agent Template — analyzing, planning, and writing code."""

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
    id="code-generation",
    name="Autonomous Software Engineer",
    description=(
        "Understand a coding request, plan the implementation, "
        "write the code, and review it for quality."
    ),
    success_criteria=[
        SuccessCriterion(
            id="requirements-met",
            description="The code fulfills the user request",
            metric="user_approval",
            target="true",
        ),
        SuccessCriterion(
            id="code-quality",
            description="Code follows best practices and is bug-free",
            metric="llm_eval",
            target="high",
        ),
    ],
    constraints=[
        Constraint(
            id="secure-code",
            description="No hardcoded secrets or vulnerabilities",
            constraint_type="hard",
            category="security",
        ),
    ],
    input_schema={
        "request": {"type": "string"},
        "context_files": {"type": "array", "optional": True},
    },
    output_schema={
        "plan": {"type": "string"},
        "code_files": {"type": "object"},  # {filename: content}
        "review_comments": {"type": "string", "optional": True},
    },
)

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
edges = [
    # Analyze -> Plan
    EdgeSpec(
        id="analyze-to-plan",
        source="analyze-request",
        target="create-plan",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Plan -> Code
    EdgeSpec(
        id="plan-to-code",
        source="create-plan",
        target="write-code",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Code -> Review
    EdgeSpec(
        id="code-to-review",
        source="write-code",
        target="review-code",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Review -> Code (Feedback loop if issues found)
    EdgeSpec(
        id="review-fix",
        source="review-code",
        target="write-code",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == False",
        description="Fix issues identified in review",
    ),
    # Review -> Finish (Approved)
    EdgeSpec(
        id="review-finish",
        source="review-code",
        target="finalize-delivery",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == True",
    ),
]

# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------
entry_node = "analyze-request"
entry_points = {"start": "analyze-request"}
terminal_nodes = ["finalize-delivery"]
nodes = all_nodes
pause_nodes = []

# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class CodingAgent:
    """Autonomous Software Engineer Agent."""

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
            id="coding-agent-graph",
            goal_id=self.goal.id,
            entry_node=entry_node,
            entry_points=entry_points,
            terminal_nodes=terminal_nodes,
            pause_nodes=pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
        )

    def _setup(self):
        from pathlib import Path
        storage_path = Path(self.config.storage_path).expanduser()
        runtime = Runtime(storage_path=storage_path)
        llm = AnthropicProvider(model=self.config.model)

        # In a real implementation, we'd add file system tools here
        tools = []

        self.executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            storage_path=storage_path
        )
        return self.executor

    async def run(self, context: dict) -> dict:
        graph = self._build_graph()
        if not self.executor:
            self._setup()

        # Ensure input data conforms to expected schema
        sanitized_context = {k: v for k, v in context.items()
                            if k in ["request", "context_files"]}

        result = await self.executor.execute(
            graph=graph,
            goal=self.goal,
            input_data=sanitized_context,
        )
        return result.output

default_agent = CodingAgent()
