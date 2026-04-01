"""Agent graph construction for Invoicing & Collections Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import COLLECTION_CONFIG, default_config, metadata
from .nodes import (
    scan_invoices_node,
    classify_overdue_node,
    send_reminders_node,
    judge_reminders_node,
    escalate_review_node,
    generate_report_node,
)

# Goal definition
goal = Goal(
    id="invoicing-collections-goal",
    name="Invoicing & Collections",
    description=(
        "Scan invoices from CSV, classify overdue accounts into aging buckets, "
        "send tiered reminder emails, validate classification accuracy, escalate "
        "high-value or severely overdue invoices for human review, and generate "
        "an AR aging report."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-classify",
            description="All unpaid invoices classified into correct aging buckets",
            metric="classification_accuracy",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-reminders",
            description="Appropriate reminders sent to 30-day and 60-day accounts",
            metric="reminder_compliance",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-escalation",
            description="High-value (>$10k) and 90+ day invoices escalated for human review",
            metric="escalation_compliance",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-report",
            description="AR aging report generated with per-bucket totals",
            metric="report_completeness",
            target="all invoices included",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-current-reminders",
            description="Never send reminders to invoices in the current bucket (0-2 days)",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="c-payment-link",
            description="All gentle reminders (3-day) must include a direct payment link",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="c-cc-account-executive",
            description="Firm reminders (15-day) must CC the assigned Account Executive",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="c-restrict-access",
            description="At 30+ days, restrict client software access via API and notify CFO",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="c-escalation-threshold",
            description="Always escalate invoices over $10,000 for human review",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="c-human-approval",
            description="No action on escalated invoices without human approval",
            constraint_type="hard",
            category="functional",
        ),
    ],
)

# Node list
nodes = [
    scan_invoices_node,
    classify_overdue_node,
    send_reminders_node,
    judge_reminders_node,
    escalate_review_node,
    generate_report_node,
]

# Edge definitions
edges = [
    # Main flow: scan → classify → send reminders → judge
    EdgeSpec(
        id="scan-to-classify",
        source="scan-invoices",
        target="classify-overdue",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-reminders",
        source="classify-overdue",
        target="send-reminders",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="reminders-to-judge",
        source="send-reminders",
        target="judge-reminders",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Judge passes → escalation review
    EdgeSpec(
        id="judge-pass-to-escalate",
        source="judge-reminders",
        target="escalate-review",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="judgment_passed == True",
        priority=1,
    ),
    # Judge fails → reclassify
    EdgeSpec(
        id="judge-fail-to-reclassify",
        source="judge-reminders",
        target="classify-overdue",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="needs_reclassification == True",
        priority=2,
    ),
    # Escalation reviewed → generate report
    EdgeSpec(
        id="escalate-to-report",
        source="escalate-review",
        target="generate-report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Report done → loop back to scan for next batch
    EdgeSpec(
        id="report-to-scan",
        source="generate-report",
        target="scan-invoices",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "scan-invoices"
entry_points = {"start": "scan-invoices"}
pause_nodes = []
terminal_nodes = []

# Module-level vars read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = (
    "You are an accounts-receivable automation agent. You process invoices, "
    "send collection reminders, and escalate high-value accounts for human review."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class InvoicingCollectionsAgent:
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
            id="invoicing-collections-graph",
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
        self._storage_path = (
            Path.home() / ".hive" / "agents" / "invoicing_collections_agent"
        )
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
                    id="default",
                    name="Default",
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
                checkpoint_max_age_days=7,
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
        entry_point="default",
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
        # Inject collection_config so downstream nodes can access it
        context.setdefault("collection_config", COLLECTION_CONFIG)
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
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
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
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
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = InvoicingCollectionsAgent()
