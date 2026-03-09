"""Agent QA Pipeline — Meta-Circular Testing with Framework Evolution Proposals.

A goal-driven agent that performs quality assessment on other Hive agents:
- Static analysis (topology, patterns, edge consistency)
- Functional testing (spec-level reasoning)
- Resilience testing (error handling patterns)
- Security auditing (OWASP LLM Top 10)

Produces PASS / CONDITIONAL / FAIL verdict with iterative fix/re-test cycles.
"""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config
from .nodes import (
    aggregate_results_node,
    deliver_report_node,
    generate_report_node,
    generate_test_plan_node,
    intake_node,
    judge_quality_node,
    load_agent_node,
    request_fixes_node,
    review_test_plan_node,
    run_functional_node,
    run_resilience_node,
    run_security_node,
    static_analysis_node,
)

goal = Goal(
    id="agent-qa-pipeline",
    name="Agent QA Pipeline",
    description=(
        "Performs quality assessment on other Hive agents through static analysis, "
        "functional testing, resilience testing, and security auditing. Produces a "
        "PASS / CONDITIONAL / FAIL verdict with iterative fix/re-test cycles."
    ),
    success_criteria=[
        SuccessCriterion(
            id="valid-agent-loaded",
            description="Successfully loads and parses the target agent spec",
            metric="agent_loaded",
            target="true",
            weight=0.1,
        ),
        SuccessCriterion(
            id="static-analysis-complete",
            description="Completes structural analysis of the agent graph",
            metric="analysis_complete",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="test-plan-approved",
            description="User reviews and approves the test plan",
            metric="plan_approved",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="all-categories-tested",
            description="Runs tests across functional, resilience, and security categories",
            metric="categories_tested",
            target=">=3",
            weight=0.25,
        ),
        SuccessCriterion(
            id="verdict-produced",
            description="Produces a quality verdict with score and actionable recommendations",
            metric="verdict_produced",
            target="true",
            weight=0.2,
        ),
        SuccessCriterion(
            id="report-delivered",
            description="Delivers a comprehensive HTML report to the user",
            metric="report_delivered",
            target="true",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="max-feedback-cycles",
            description="Limit feedback cycles to prevent infinite loops",
            constraint_type="hard",
            category="behavioral",
        ),
        Constraint(
            id="graceful-error-handling",
            description="If agent loading fails, produce an error report instead of crashing",
            constraint_type="hard",
            category="reliability",
        ),
        Constraint(
            id="no-actual-exploits",
            description="Security testing must only analyze patterns, not attempt actual exploits",
            constraint_type="hard",
            category="safety",
        ),
    ],
)

nodes = [
    intake_node,
    load_agent_node,
    static_analysis_node,
    generate_test_plan_node,
    review_test_plan_node,
    run_functional_node,
    run_resilience_node,
    run_security_node,
    aggregate_results_node,
    judge_quality_node,
    generate_report_node,
    deliver_report_node,
    request_fixes_node,
]

edges = [
    EdgeSpec(
        id="intake-to-load-agent",
        source="intake",
        target="load-agent",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="load-agent-to-static-analysis",
        source="load-agent",
        target="static-analysis",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="load-agent-to-generate-report-on-failure",
        source="load-agent",
        target="generate-report",
        condition=EdgeCondition.ON_FAILURE,
        priority=1,
    ),
    EdgeSpec(
        id="static-analysis-to-generate-test-plan",
        source="static-analysis",
        target="generate-test-plan",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="generate-test-plan-to-review-test-plan",
        source="generate-test-plan",
        target="review-test-plan",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-test-plan-to-run-functional",
        source="review-test-plan",
        target="run-functional",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-test-plan-to-run-resilience",
        source="review-test-plan",
        target="run-resilience",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-test-plan-to-run-security",
        source="review-test-plan",
        target="run-security",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="run-functional-to-aggregate-results",
        source="run-functional",
        target="aggregate-results",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="run-resilience-to-aggregate-results",
        source="run-resilience",
        target="aggregate-results",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="run-security-to-aggregate-results",
        source="run-security",
        target="aggregate-results",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="aggregate-results-to-judge-quality",
        source="aggregate-results",
        target="judge-quality",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="judge-quality-to-generate-report-pass-fail",
        source="judge-quality",
        target="generate-report",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="verdict in ['PASS', 'FAIL']",
        priority=1,
    ),
    EdgeSpec(
        id="judge-quality-to-request-fixes-conditional",
        source="judge-quality",
        target="request-fixes",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="verdict == 'CONDITIONAL'",
        priority=2,
    ),
    EdgeSpec(
        id="generate-report-to-deliver-report",
        source="generate-report",
        target="deliver-report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="request-fixes-to-load-agent",
        source="request-fixes",
        target="load-agent",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(continue_testing).lower() == 'true'",
        priority=-1,
    ),
    EdgeSpec(
        id="request-fixes-to-generate-report",
        source="request-fixes",
        target="generate-report",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(continue_testing).lower() != 'true'",
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {
    "start": "intake",
    "resume_from_review": "review-test-plan",
    "resume_from_fixes": "request-fixes",
}
pause_nodes = ["review-test-plan"]
terminal_nodes = ["deliver-report"]


class AgentQAPipelineAgent:
    """
    Agent QA Pipeline — Meta-Circular Testing with Framework Evolution Proposals.

    A 13-node pipeline for quality assessment of other Hive agents.
    Demonstrates: fan-out/fan-in, HITL pause, conditional routing,
    feedback loops, and on_failure edges.
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
            id="agent-qa-pipeline-graph",
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
                "You are an Agent QA Pipeline. You analyze other Hive agents "
                "for quality, correctness, resilience, and security. You produce "
                "letter-grade scores (A-F) and actionable recommendations."
            ),
        )

    def _setup(self, mock_mode=False) -> None:
        self._storage_path = Path.home() / ".hive" / "agents" / "agent_qa_pipeline"
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

    def validate(self):
        errors = []
        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        return {"valid": len(errors) == 0, "errors": errors}


default_agent = AgentQAPipelineAgent()
