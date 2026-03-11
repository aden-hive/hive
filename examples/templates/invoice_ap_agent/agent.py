"""Agent graph construction for Invoice & AP Automation Agent.

End-to-end accounts payable intelligence: extract invoice data using LLM-powered
parsing, validate against purchase orders, flag discrepancies, route for human
approval, and post confirmed entries to accounting systems.
"""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    digest_node,
    extraction_node,
    hitl_review_node,
    intake_node,
    post_node,
    routing_node,
    validation_node,
)

goal = Goal(
    id="invoice-ap-automation",
    name="Invoice & AP Automation Agent",
    description=(
        "End-to-end accounts payable intelligence: monitor incoming invoices, "
        "extract structured data, validate against POs, route for approval, "
        "and post to accounting systems."
    ),
    success_criteria=[
        SuccessCriterion(
            id="extraction-accuracy",
            description="Invoice data extraction accuracy",
            metric="field_extraction_accuracy",
            target=">=92%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="discrepancy-detection",
            description="Discrepancy detection rate on mismatched PO amounts",
            metric="discrepancy_detection_rate",
            target=">=95%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="human-confirmation",
            description="Human confirmation before accounting entry",
            metric="human_confirmation_rate",
            target="100%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="processing-time",
            description="Processing time per invoice reduced from manual",
            metric="processing_time_minutes",
            target="<2",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="mandatory-hitl",
            description="No accounting entry without human approval gate",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="data-privacy",
            description="Vendor financial data must be handled securely",
            constraint_type="hard",
            category="security",
        ),
        Constraint(
            id="audit-trail",
            description="Full audit trail required for all invoice decisions",
            constraint_type="hard",
            category="compliance",
        ),
    ],
)

nodes = [
    intake_node,
    extraction_node,
    validation_node,
    hitl_review_node,
    routing_node,
    post_node,
    digest_node,
]

edges = [
    EdgeSpec(
        id="intake-to-extraction",
        source="intake",
        target="extraction",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="extraction-to-validation",
        source="extraction",
        target="validation",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="validation-to-hitl",
        source="validation",
        target="hitl-review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="hitl-to-routing-approved",
        source="hitl-review",
        target="routing",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approval_decision == 'approved'",
        priority=1,
    ),
    EdgeSpec(
        id="hitl-to-digest-rejected",
        source="hitl-review",
        target="digest",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approval_decision == 'rejected'",
        priority=2,
    ),
    EdgeSpec(
        id="hitl-to-digest-hold",
        source="hitl-review",
        target="digest",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approval_decision == 'hold'",
        priority=3,
    ),
    EdgeSpec(
        id="routing-to-post",
        source="routing",
        target="post",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="post-to-digest",
        source="post",
        target="digest",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["digest"]

conversation_mode = "continuous"
identity_prompt = (
    "You are an accounts payable automation assistant that processes invoices, "
    "validates against purchase orders, routes for human approval, and posts to accounting."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class InvoiceAPAgent:
    """Invoice & AP Automation Agent for end-to-end accounts payable processing.

    Pipeline: intake -> extraction -> validation -> hitl_review -> routing -> post -> digest

    Human-in-the-loop gate at hitl_review ensures 100% human confirmation before
    any accounting entry is posted.
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
        self._graph = None
        self._agent_runtime = None
        self._tool_registry = None
        self._storage_path = None

    def _build_graph(self):
        return GraphSpec(
            id="invoice-ap-graph",
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

    def _setup(self):
        self._storage_path = Path.home() / ".hive" / "agents" / "invoice_ap_agent"
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._tool_registry = ToolRegistry()
        mcp_config = Path(__file__).parent / "mcp_servers.json"
        if mcp_config.exists():
            self._tool_registry.load_mcp_config(mcp_config)
        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )
        tools = list(self._tool_registry.get_tools().values())
        tool_executor = self._tool_registry.get_executor()
        self._graph = self._build_graph()
        self._agent_runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Process Invoice",
                    entry_node=self.entry_node,
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(
                enabled=True,
                checkpoint_on_node_complete=True,
                checkpoint_max_age_days=30,
                async_checkpoint=True,
            ),
        )

    async def start(self):
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self):
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def trigger_and_wait(
        self,
        entry_point="start",
        input_data=None,
        timeout=None,
        session_state=None,
    ):
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")
        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data or {},
            session_state=session_state,
        )

    async def run(self, context, session_state=None):
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
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
            "terminal_nodes": self.terminal_nodes,
            "pause_nodes": self.pause_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
            "hitl_gate": "hitl-review",
        }

    def validate(self):
        errors, warnings = [], []
        node_ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in node_ids:
                errors.append(f"Edge {e.id}: source '{e.source}' not found")
            if e.target not in node_ids:
                errors.append(f"Edge {e.id}: target '{e.target}' not found")
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        for t in self.terminal_nodes:
            if t not in node_ids:
                errors.append(f"Terminal node '{t}' not found")
        for ep_id, nid in self.entry_points.items():
            if nid not in node_ids:
                errors.append(f"Entry point '{ep_id}' references unknown node '{nid}'")
        if "hitl-review" not in node_ids:
            warnings.append(
                "HITL gate node 'hitl-review' not found - human confirmation required"
            )
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = InvoiceAPAgent()
