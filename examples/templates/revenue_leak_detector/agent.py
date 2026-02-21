"""Revenue Leak Detector Agent — LLM-driven event_loop nodes.

Graph topology
--------------
  monitor ──► analyze ──► notify ──► followup
                                           │
              ◄───────────────────────────┘  (loop while halt != true)

The agent runs until severity hits critical or MAX_CYCLES low-severity
cycles have elapsed without leaks.
"""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import monitor_node, analyze_node, notify_node, followup_node

# ---- Goal ----
goal = Goal(
    id="revenue-leak-detector",
    name="Revenue Leak Detector",
    description=(
        "Autonomous business health monitor that continuously scans the CRM pipeline, "
        "detects revenue leaks (ghosted prospects, stalled deals, overdue payments, "
        "churn risk), and sends structured alerts until a critical leak threshold "
        "triggers escalation."
    ),
)

# ---- Nodes ----
nodes = [monitor_node, analyze_node, notify_node, followup_node]

# ---- Edges ----
edges = [
    # monitor → analyze (always proceed to analysis after scanning)
    EdgeSpec(
        id="monitor-to-analyze",
        source="monitor",
        target="analyze",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # analyze → notify (always send alert after analysis)
    EdgeSpec(
        id="analyze-to-notify",
        source="analyze",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # notify → followup (always send follow-up emails after alerting)
    EdgeSpec(
        id="notify-to-followup",
        source="notify",
        target="followup",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # followup → monitor (loop back while not halted)
    EdgeSpec(
        id="followup-to-monitor",
        source="followup",
        target="monitor",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr='str(halt).lower() != "true"',
        priority=1,
    ),
]

entry_node = "monitor"
entry_points = {"start": "monitor"}
terminal_nodes = []
pause_nodes = []


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class RevenuLeakDetectorAgent:
    """
    Revenue Leak Detector Agent — 4-node event_loop pipeline.

    Flow: monitor -> analyze -> notify -> followup (loops until halt)

    Uses AgentRuntime for proper session management with checkpointing
    and session-isolated tool state via contextvars.
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
            id="revenue-leak-detector-graph",
            goal_id=self.goal.id,
            version="1.0.0",
            entry_node=self.entry_node,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start Monitoring",
                    entry_node=self.entry_node,
                    trigger_type="manual",
                    isolation_level="isolated",
                )
            ],
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
                "You are an autonomous revenue operations monitor. You scan CRM pipelines, "
                "detect revenue leaks, send structured alerts, and follow up with ghosted "
                "prospects. You are precise, data-driven, and escalate critical issues immediately."
            ),
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the agent runtime with tools, LLM, and session storage."""
        self._storage_path = Path.home() / ".hive" / "agents" / "revenue_leak_detector"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        # Register tools from tools.py via TOOLS dict + tool_executor pattern
        tools_path = Path(__file__).parent / "tools.py"
        self._tool_registry.discover_from_module(tools_path)

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

        self._agent_runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start Monitoring",
                    entry_node=self.entry_node,
                    trigger_type="manual",
                    isolation_level="isolated",
                )
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
        )

    async def start(self, mock_mode: bool = False) -> None:
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
        entry_point: str = "start",
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
        self, context: dict | None = None, mock_mode: bool = False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "start", context or {"cycle": "0"}, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> dict:
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

    def validate(self) -> dict:
        """Validate agent structure."""
        errors: list[str] = []
        warnings: list[str] = []

        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")

        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = RevenuLeakDetectorAgent()

__all__ = [
    "RevenuLeakDetectorAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
]
