"""Agent graph construction for Churn Risk Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    signal_intake_node,
    risk_scoring_node,
    routing_node,
    escalation_node,
    outreach_node,
    monitor_node,
    output_node,
)

# Goal definition
goal = Goal(
    id="churn-risk-detection",
    name="Churn Risk Detection and Retention",
    description=(
        "Monitor customer engagement signals, detect churn risk, "
        "and trigger appropriate retention actions with human-in-the-loop approval."
    ),
    success_criteria=[
        SuccessCriterion(
            id="risk-scored",
            description="Every account receives a risk score with criterion-by-criterion reasoning",
            metric="risk_score_produced",
            target="true",
            weight=0.30,
        ),
        SuccessCriterion(
            id="correct-routing",
            description="Account is routed to the correct action based on risk level",
            metric="routing_matches_risk_level",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="hitl-gate",
            description="No outreach is sent without human review and approval",
            metric="human_approved_before_send",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="audit-trail",
            description="A complete audit log is produced for every run",
            metric="audit_log_produced",
            target="true",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="no-send-without-approval",
            description="Never send outreach without explicit human approval",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="reasoning-required",
            description="Every risk score must include criterion-by-criterion reasoning",
            constraint_type="hard",
            category="accuracy",
        ),
        Constraint(
            id="signal-based-only",
            description="Risk assessment must be based only on provided account signals",
            constraint_type="hard",
            category="accuracy",
        ),
    ],
)

# Node list
nodes = [
    signal_intake_node,
    risk_scoring_node,
    routing_node,
    escalation_node,
    outreach_node,
    monitor_node,
    output_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-scoring",
        source="signal_intake",
        target="risk_scoring",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="scoring-to-routing",
        source="risk_scoring",
        target="routing",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="routing-to-escalation",
        source="routing",
        target="escalation",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="routing_decision == 'escalate'",
        priority=1,
    ),
    EdgeSpec(
        id="routing-to-outreach",
        source="routing",
        target="outreach",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="routing_decision == 'outreach'",
        priority=1,
    ),
    EdgeSpec(
        id="routing-to-monitor",
        source="routing",
        target="monitor",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="routing_decision == 'monitor'",
        priority=1,
    ),
    EdgeSpec(
        id="escalation-to-output",
        source="escalation",
        target="output",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="outreach-to-output",
        source="outreach",
        target="output",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="monitor-to-output",
        source="monitor",
        target="output",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "signal_intake"
entry_points = {"start": "signal_intake"}
pause_nodes = []
terminal_nodes = ["output"]

# Module-level vars
conversation_mode = "continuous"
identity_prompt = (
    "You are a churn risk detection agent that analyses customer engagement signals, "
    "scores churn risk, and triggers retention actions with human approval."
)
loop_config = {
    "max_iterations": 10,
    "max_tool_calls_per_turn": 5,
    "max_history_tokens": 16000,
}



class ChurnRiskAgent:
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
            id="churn-risk-agent-graph",
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
        self._storage_path = Path.home() / ".hive" / "agents" / "churn_risk_agent"
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
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "default",
                context,
                session_state=session_state,
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


default_agent = ChurnRiskAgent()
