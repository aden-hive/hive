"""Support Debugger Agent — goal, edges, graph spec, and agent class."""

from framework.graph import EdgeCondition, EdgeSpec, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import all_nodes

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------
goal = Goal(
    id="support-debugging",
    name="Support Ticket Debugging",
    description=(
        "Investigate a technical support ticket by building context, generating "
        "competing hypotheses, gathering evidence through available tools, and "
        "producing a root-cause analysis with actionable fix steps."
    ),
    success_criteria=[
        SuccessCriterion(
            id="root-cause-identified",
            description="A specific root cause is identified with supporting evidence",
            metric="root_cause_present",
            target="true",
            weight=0.3,
        ),
        SuccessCriterion(
            id="evidence-backed",
            description="The conclusion is backed by at least one piece of tool-gathered evidence",
            metric="evidence_count",
            target=">=1",
            weight=0.25,
        ),
        SuccessCriterion(
            id="confidence-threshold",
            description="Top hypothesis confidence reaches 0.9 or above",
            metric="top_confidence",
            target=">=0.9",
            weight=0.2,
        ),
        SuccessCriterion(
            id="fix-steps-provided",
            description="Actionable fix steps are provided in the final response",
            metric="fix_steps_present",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="no-hallucinated-fixes",
            description="Fix steps must be grounded in gathered evidence, not invented",
            constraint_type="hard",
            category="accuracy",
        ),
        Constraint(
            id="evidence-required",
            description="Do not conclude without at least one tool-gathered evidence item",
            constraint_type="hard",
            category="accuracy",
        ),
        Constraint(
            id="bounded-investigation",
            description="Investigation loop must terminate within max_node_visits iterations",
            constraint_type="hard",
            category="safety",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
edges = [
    EdgeSpec(
        id="context-to-hypotheses",
        source="build-context",
        target="generate-hypotheses",
        condition=EdgeCondition.ON_SUCCESS,
        description="After context extraction, generate hypotheses",
    ),
    EdgeSpec(
        id="hypotheses-to-investigate",
        source="generate-hypotheses",
        target="investigate",
        condition=EdgeCondition.ON_SUCCESS,
        description="After hypotheses are generated, begin investigation",
    ),
    EdgeSpec(
        id="investigate-to-refine",
        source="investigate",
        target="refine-hypotheses",
        condition=EdgeCondition.ON_SUCCESS,
        description="After evidence gathering, refine hypothesis confidence",
    ),
    EdgeSpec(
        id="refine-to-investigate",
        source="refine-hypotheses",
        target="investigate",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='output["investigation_complete"] == False',
        priority=10,
        description="Loop back to investigate if confidence has not converged",
    ),
    EdgeSpec(
        id="refine-to-response",
        source="refine-hypotheses",
        target="generate-response",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='output["investigation_complete"] == True',
        priority=1,
        description="Exit to response generation when investigation is complete",
    ),
]

# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------
entry_node = "build-context"
entry_points = {"start": "build-context"}
terminal_nodes = ["generate-response"]
pause_nodes = []
nodes = all_nodes


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class SupportDebuggerAgent:
    """
    Support Debugger Agent — hypothesis-driven investigation loop.

    Flow:
        build-context → generate-hypotheses → investigate → refine-hypotheses
                                                   ↑               │
                                                   └── (not done) ─┘
                                                           │
                                                      (done)
                                                           ↓
                                                   generate-response → END
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
        self._executor: GraphExecutor | None = None
        self._graph: GraphSpec | None = None
        self._event_bus: EventBus | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec from declared nodes and edges."""
        return GraphSpec(
            id="support-debugger-graph",
            goal_id=self.goal.id,
            version="0.1.0",
            entry_node=self.entry_node,
            entry_points=self.entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=self.pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            description="Hypothesis-driven support ticket debugging workflow",
            loop_config={
                "max_iterations": 50,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self, mock_mode=False) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "support_debugger"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        # Discover @tool-decorated functions from tools.py
        tools_path = Path(__file__).parent / "tools.py"
        self._tool_registry.discover_from_module(tools_path)

        llm = None
        if not mock_mode:
            llm = LiteLLMProvider(
                model=self.config.model,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
            )
        else:
            from framework.llm.mock import MockLLMProvider

            llm = MockLLMProvider()

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()
        runtime = Runtime(storage_path)

        self._executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            event_bus=self._event_bus,
            storage_path=storage_path,
            loop_config=self._graph.loop_config,
        )

        return self._executor

    async def start(self, mock_mode=False) -> None:
        """Set up the agent (initialize executor and tools)."""
        if self._executor is None:
            self._setup(mock_mode=mock_mode)

    async def stop(self) -> None:
        """Clean up resources."""
        self._executor = None
        self._event_bus = None

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
        if self._executor is None:
            raise RuntimeError("Agent not started. Call start() first.")
        if self._graph is None:
            raise RuntimeError("Graph not built. Call start() first.")

        return await self._executor.execute(
            graph=self._graph,
            goal=self.goal,
            input_data=input_data,
            session_state=session_state,
        )

    async def run(
        self, context: dict, mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
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

        # Validate edge references
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")

        # Validate entry node
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")

        # Validate terminal nodes
        for terminal in self.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node '{terminal}' not found")

        # Validate entry points
        for ep_id, node_id in self.entry_points.items():
            if node_id not in node_ids:
                errors.append(
                    f"Entry point '{ep_id}' references unknown node '{node_id}'"
                )

        # Validate conditional edges have expressions
        for edge in self.edges:
            if edge.condition == EdgeCondition.CONDITIONAL and not edge.condition_expr:
                errors.append(
                    f"Edge {edge.id}: CONDITIONAL edge missing condition_expr"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Default instance
default_agent = SupportDebuggerAgent()
