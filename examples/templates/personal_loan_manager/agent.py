"""Agent graph construction for Personal Loan Manager."""

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

# In a full production setup, these would be wrapped in Hive Node classes.
# For this architectural draft, we are defining the graph structure to show the workflow.
class DraftNode:
    def __init__(self, id): self.id = id
    @property
    def client_facing(self): return False

intake_node = DraftNode("intake")
kyc_node = DraftNode("kyc_verification")
credit_node = DraftNode("credit_analysis")
report_node = DraftNode("decision_report")

# Goal definition
goal = Goal(
    id="bfsi-loan-approval",
    name="BFSI Personal Loan Approval Orchestrator",
    description=(
        "Automate personal loan approvals by verifying KYC documents "
        "and analyzing credit risk before generating a final decision."
    ),
    success_criteria=[
        SuccessCriterion(
            id="kyc-compliance",
            description="Applicant must pass all AML and identity checks",
            metric="kyc_status",
            target="PASS",
            weight=0.50,
        ),
        SuccessCriterion(
            id="credit-risk-assessed",
            description="Applicant must receive a valid credit risk tier",
            metric="risk_category",
            target="Low|Medium",
            weight=0.50,
        ),
    ],
    constraints=[
        Constraint(
            id="strict-financial-accuracy",
            description="Never hallucinate credit scores; only use verified financial data.",
            constraint_type="quality",
            category="accuracy",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    kyc_node,
    credit_node,
    report_node,
]

# Edge definitions (The routing logic)
edges = [
    # intake -> KYC
    EdgeSpec(
        id="intake-to-kyc",
        source="intake",
        target="kyc_verification",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # KYC -> Credit (Only if KYC Passes)
    EdgeSpec(
        id="kyc-to-credit",
        source="kyc_verification",
        target="credit_analysis",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="kyc_status == 'PASS'",
        priority=1,
    ),
    # KYC -> Report (If KYC Fails, skip credit check and reject)
    EdgeSpec(
        id="kyc-to-report-fail",
        source="kyc_verification",
        target="decision_report",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="kyc_status != 'PASS'",
        priority=2,
    ),
    # Credit -> Report
    EdgeSpec(
        id="credit-to-report",
        source="credit_analysis",
        target="decision_report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["decision_report"]


class PersonalLoanManagerAgent:
    """
    BFSI Personal Loan Manager - 4-node pipeline.
    Flow: intake -> kyc_verification -> credit_analysis -> decision_report
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
            id="personal-loan-manager-graph",
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
        storage_path = Path.home() / ".hive" / "agents" / "personal_loan_manager"
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

# Create default instance
default_agent = PersonalLoanManagerAgent()