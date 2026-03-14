"""Agent graph construction for Security Code Scanner Agent.

A 5-node security audit pipeline:
  intake → static_analysis → risk_assessment → review → report
                                                  ↑        |
                                                  +-- feedback loop

Demonstrates:
  - Multi-node pipeline with conditional feedback loops
  - CRITICAL/HIGH/MEDIUM/LOW severity categorization
  - Professional HTML report generation
  - Client-facing checkpoints for user review
"""

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
    static_analysis_node,
    risk_assessment_node,
    review_node,
    report_node,
)

# Goal definition
goal = Goal(
    id="automated-security-audit",
    name="Automated Security Audit",
    description=(
        "Scan a codebase for security vulnerabilities, score risks by exploitability "
        "and impact, and produce a professional audit report with prioritized remediation."
    ),
    success_criteria=[
        SuccessCriterion(
            id="vulnerability-coverage",
            description="Check all OWASP Top 10 vulnerability categories",
            metric="category_coverage",
            target=">=8",
            weight=0.25,
        ),
        SuccessCriterion(
            id="risk-scoring",
            description="Every finding has a justified risk score",
            metric="scored_findings",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="actionable-fixes",
            description="Every finding includes a specific remediation recommendation",
            metric="fix_coverage",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="report-quality",
            description="Report is professional, well-structured, and client-ready",
            metric="report_generated",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="no-false-positives",
            description="Only report findings that are verifiable in the source code",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="severity-justification",
            description="Each severity rating must be justified with exploitability and impact analysis",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="user-review",
            description="Present findings to the user before generating the final report",
            constraint_type="functional",
            category="interaction",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    static_analysis_node,
    risk_assessment_node,
    review_node,
    report_node,
]

# Edge definitions
edges = [
    # intake → static_analysis
    EdgeSpec(
        id="intake-to-analysis",
        source="intake",
        target="static_analysis",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # static_analysis → risk_assessment
    EdgeSpec(
        id="analysis-to-risk",
        source="static_analysis",
        target="risk_assessment",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # risk_assessment → review
    EdgeSpec(
        id="risk-to-review",
        source="risk_assessment",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # review → report (user approved)
    EdgeSpec(
        id="review-to-report",
        source="review",
        target="report",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == True",
        priority=2,
    ),
    # review → static_analysis (feedback loop — user wants deeper analysis)
    EdgeSpec(
        id="review-to-analysis-feedback",
        source="review",
        target="static_analysis",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == False",
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["report"]


class SecurityScannerAgent:
    """
    Security Code Scanner Agent — 5-node audit pipeline.

    Flow: intake → static_analysis → risk_assessment → review → report
                         ↑                                |
                         +---------- feedback loop -------+

    Uses AgentRuntime for:
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
            id="security-scanner-agent-graph",
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
                "max_tool_calls_per_turn": 20,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "security_scanner_agent"
        storage_path.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_path

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

        # Security-specific validations
        client_facing = [n for n in self.nodes if n.client_facing]
        if not client_facing:
            warnings.append("No client-facing nodes — user won't have review checkpoints")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = SecurityScannerAgent()
