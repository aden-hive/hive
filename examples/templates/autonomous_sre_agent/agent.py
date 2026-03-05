"""Agent graph construction for Autonomous SRE Incident Resolution Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    alert_intake_node,
    log_fetch_node,
    incident_analyzer_node,
    severity_estimator_node,
    auto_resolve_node,
    escalate_node,
    outcome_store_node,
)

goal = Goal(
    id="autonomous-sre-incident-resolution",
    name="Autonomous SRE Incident Resolution",
    description=(
        "Accept a production alert, fetch logs, analyze root cause, estimate confidence, "
        "auto-resolve if confidence >= 80 and severity != critical, otherwise escalate "
        "to human with full investigation summary. Store outcome for future learning."
    ),
    success_criteria=[
        SuccessCriterion(
            id="root-cause-identified",
            description="Root cause identified from log analysis",
            metric="root_cause_identified",
            target="true",
            weight=0.30,
        ),
        SuccessCriterion(
            id="confidence-scored",
            description="Confidence score (0-100) produced for root cause accuracy",
            metric="confidence_scored",
            target="true",
            weight=0.20,
        ),
        SuccessCriterion(
            id="correct-routing",
            description="Incident routed to auto-resolve or escalation based on confidence and severity",
            metric="routing_correct",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="outcome-stored",
            description="Incident outcome stored in long-term memory",
            metric="outcome_stored",
            target="true",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="never-auto-resolve-critical",
            description="Critical severity incidents must always be escalated to a human, never auto-resolved",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="confidence-threshold",
            description="Auto-resolution only permitted when confidence >= 80",
            constraint_type="hard",
            category="safety",
        ),
    ],
)

nodes = [
    alert_intake_node,
    log_fetch_node,
    incident_analyzer_node,
    severity_estimator_node,
    auto_resolve_node,
    escalate_node,
    outcome_store_node,
]

edges = [
    EdgeSpec(
        id="intake-to-log-fetch",
        source="alert-intake",
        target="log-fetch",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="log-fetch-to-analyzer",
        source="log-fetch",
        target="incident-analyzer",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="analyzer-to-severity",
        source="incident-analyzer",
        target="severity-estimator",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Conditional: high confidence + non-critical → auto-resolve
    EdgeSpec(
        id="severity-to-auto-resolve",
        source="severity-estimator",
        target="auto-resolve",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="int(confidence) >= 80 and str(severity).lower() != 'critical'",
        priority=1,
    ),
    # Conditional: low confidence OR critical → escalate
    EdgeSpec(
        id="severity-to-escalate",
        source="severity-estimator",
        target="escalate",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="int(confidence) < 80 or str(severity).lower() == 'critical'",
        priority=1,
    ),
    EdgeSpec(
        id="auto-resolve-to-outcome",
        source="auto-resolve",
        target="outcome-store",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="escalate-to-outcome",
        source="escalate",
        target="outcome-store",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Forever-alive: loop back for next alert
    EdgeSpec(
        id="outcome-to-intake",
        source="outcome-store",
        target="alert-intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=-1,
    ),
]

entry_node = "alert-intake"
entry_points = {"start": "alert-intake"}
pause_nodes = []
terminal_nodes = []


class AutonomousSREAgent:
    """
    Autonomous SRE Incident Resolution — forever-alive agent.

    Flow: alert-intake → log-fetch → incident-analyzer → severity-estimator
                                                               ↓              ↓
                                                        (conf>=80,        (conf<80 OR
                                                        !critical)         critical)
                                                               ↓              ↓
                                                        auto-resolve     escalate
                                                               ↓              ↓
                                                          outcome-store ←──────┘
                                                               ↓
                                                    alert-intake (forever-alive)
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
        return GraphSpec(
            id="autonomous-sre-graph",
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
            conversation_mode="continuous",
            identity_prompt=(
                "You are an autonomous SRE incident resolution agent. You analyze "
                "production alerts, fetch logs, identify root causes, score your "
                "confidence, and either auto-resolve incidents or escalate to human "
                "engineers with a full investigation summary."
            ),
        )

    def _setup(self, mock_mode=False) -> GraphExecutor:
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "agents" / "autonomous_sre"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        # Register mock tools
        from .tools import (
            fetch_mock_logs,
            get_similar_incidents,
            draft_slack_message,
            draft_jira_ticket,
            store_incident_outcome,
        )
        for fn in [fetch_mock_logs, get_similar_incidents, draft_slack_message,
                   draft_jira_ticket, store_incident_outcome]:
            self._tool_registry.register_function(fn)

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
        if self._executor is None:
            self._setup(mock_mode=mock_mode)

    async def stop(self) -> None:
        self._executor = None
        self._event_bus = None

    async def trigger_and_wait(self, entry_point, input_data, timeout=None, session_state=None):
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

    async def run(self, context, mock_mode=False, session_state=None):
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait("start", context, session_state=session_state)
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
        return {
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": {"name": self.goal.name, "description": self.goal.description},
            "nodes": [n.id for n in self.nodes],
            "edges": [e.id for e in self.edges],
            "entry_node": self.entry_node,
            "entry_points": self.entry_points,
            "pause_nodes": self.pause_nodes,
            "terminal_nodes": self.terminal_nodes,
            "client_facing_nodes": [n.id for n in self.nodes if n.client_facing],
        }

    def validate(self):
        errors, warnings = [], []
        node_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        for node_id in node_ids:
            if not [e for e in self.edges if e.source == node_id] and node_id not in self.terminal_nodes:
                warnings.append(f"Node '{node_id}' has no outgoing edges")
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = AutonomousSREAgent()
