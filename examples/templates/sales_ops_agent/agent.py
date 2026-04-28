"""Agent graph construction for Sales Ops Agent."""

from pathlib import Path

from framework.host.agent_host import AgentHost
from framework.host.execution_manager import EntryPointSpec
from framework.llm import LiteLLMProvider
from framework.loader.tool_registry import ToolRegistry
from framework.orchestrator import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.orchestrator.checkpoint_config import CheckpointConfig
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.orchestrator import ExecutionResult

from .config import default_config, metadata
from .nodes import (
    analyze_node,
    log_node,
    monitor_node,
    rebalance_node,
    trigger_node,
)

# Goal definition
goal = Goal(
    id="sales-ops-agent",
    name="Sales Ops Agent",
    description=(
        "Automated sales territory rebalancing. Runs monthly on the 1st to analyze "
        "sales performance metrics, detect under-allocated territories (less than "
        "20% untouched ICP accounts), and rebalance accounts from unassigned pools "
        "to ensure fair opportunity distribution across the sales team."
    ),
    success_criteria=[
        SuccessCriterion(
            id="territory-coverage",
            description=(
                "Sales territories are analyzed and reps with less than 20% untouched "
                "accounts are correctly identified for rebalancing."
            ),
            metric="coverage_detection_accuracy",
            target=">=95%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="rebalance-completion",
            description=(
                "Available unassigned accounts are successfully reassigned to "
                "under-allocated reps respecting territory constraints."
            ),
            metric="rebalance_completion_rate",
            target="100%",
            weight=0.35,
        ),
        SuccessCriterion(
            id="crm-logging",
            description=(
                "All rebalance actions are logged to the CRM with proper audit trail "
                "including timestamp, affected accounts, and owner changes."
            ),
            metric="crm_log_success_rate",
            target="100%",
            weight=0.35,
        ),
    ],
    constraints=[
        Constraint(
            id="respect-territory",
            description="Accounts must only be reassigned to reps within matching territories/regions.",
            constraint_type="hard",
            category="operational",
        ),
        Constraint(
            id="no-duplicates",
            description="The same account must never be assigned to multiple reps.",
            constraint_type="hard",
            category="operational",
        ),
        Constraint(
            id="audit-trail",
            description="All account reassignments must be logged to the CRM for compliance.",
            constraint_type="hard",
            category="compliance",
        ),
        Constraint(
            id="first-of-month-only",
            description="The agent should only perform rebalancing on the 1st of the month.",
            constraint_type="soft",
            category="operational",
        ),
    ],
)

# Node list
nodes = [
    trigger_node,
    monitor_node,
    analyze_node,
    rebalance_node,
    log_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="trigger-to-monitor",
        source="trigger",
        target="monitor",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="monitor-to-analyze",
        source="monitor",
        target="analyze",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="analyze-to-rebalance",
        source="analyze",
        target="rebalance",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="rebalance-to-log",
        source="rebalance",
        target="log",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "trigger"
entry_points = {"start": "trigger"}
async_entry_points: list = []
pause_nodes = []
terminal_nodes = ["log"]
loop_config = {
    "max_iterations": 50,
    "max_tool_calls_per_turn": 30,
    "max_tool_result_chars": 8000,
    "max_history_tokens": 32000,
}
conversation_mode = "continuous"
identity_prompt = (
    "You are a Sales Operations assistant. You help maintain fair and balanced "
    "territory distribution across the sales team. On the 1st of each month, you "
    "analyze pipeline metrics, win rates, and TAM coverage, then reassign accounts "
    "from unassigned pools to reps who need more opportunities. All actions are "
    "logged to the CRM for auditability. You support both Salesforce and HubSpot."
)


class SalesOpsAgent:
    """
    Sales Ops Agent — 5-node pipeline for automated territory rebalancing.

    Flow: trigger -> monitor -> analyze -> rebalance -> log

    Pipeline:
    1. trigger: Check if today is the 1st of the month
    2. monitor: Fetch sales data from CRM (reps, accounts, pipeline)
    3. analyze: Compute metrics and flag under-allocated reps (<20% untouched)
    4. rebalance: Reassign accounts from unassigned pool to flagged reps
    5. log: Log actions to CRM and present summary to user
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
        self._agent_runtime: AgentHost | None = None
        self._graph: GraphSpec | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="sales-ops-agent-graph",
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
        self._storage_path = Path.home() / ".hive" / "agents" / "sales_ops_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        # Skip MCP in mock mode to avoid cleanup timeouts
        if not mock_mode:
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
            checkpoint_max_age_days=30,
            async_checkpoint=True,
        )


        self._agent_runtime = AgentHost(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
        )

        self._agent_runtime.register_entry_point(EntryPointSpec(
            id="default",
            name="Default",
            entry_node=self.entry_node,
            trigger_type="manual",
            isolation_level="shared",
        ))

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

    async def run(self, context: dict, mock_mode=False, session_state=None) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait("default", context, session_state=session_state)
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
                errors.append(f"Entry point '{ep_id}' references unknown node '{node_id}'")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = SalesOpsAgent()
