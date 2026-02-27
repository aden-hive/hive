"""HubSpot Revenue Leak Detector Agent — LLM-driven event_loop nodes.

Graph topology
--------------
  monitor ──► analyze ──► notify ──► followup
                                           │
              ◄───────────────────────────┘  (loop while halt != true)

The agent runs until severity hits critical or MAX_CYCLES low-severity
cycles have elapsed without leaks.
"""

import os
from pathlib import Path
from types import MappingProxyType
from typing import List, Optional

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.llm.mock import MockLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata, VERSION
from .nodes import monitor_node, analyze_node, notify_node, followup_node

# This agent requires Resend for follow-up emails.
# The global CredentialSpec has required=False (optional for other agents),
# so we override it here at module load time so AgentRunner / TUI enforces it.
try:
    from aden_tools.credentials import CREDENTIAL_SPECS as _CRED_SPECS
    if "resend" in _CRED_SPECS:
        _CRED_SPECS["resend"].required = True
except ImportError:
    pass

# ---- Goal ----
goal = Goal(
    id="hubspot-revenue-leak-detector",
    name="HubSpot Revenue Leak Detector",
    description=(
        "Autonomous HubSpot CRM monitor that continuously scans the sales pipeline, "
        "detects revenue leaks (ghosted prospects, stalled deals, overdue payments, "
        "churn risk), and sends structured alerts until a critical leak threshold "
        "triggers escalation. Requires HUBSPOT_ACCESS_TOKEN."
    ),
    success_criteria=[
        SuccessCriterion(
            id="leak-detection",
            description="Detect all revenue leaks in the HubSpot pipeline each cycle",
            metric="output_contains",
            target="leak_count",
            weight=0.4,
        ),
        SuccessCriterion(
            id="alert-delivery",
            description="Successfully send alerts for every detected leak via console and Telegram",
            metric="output_contains",
            target="sent",
            weight=0.3,
        ),
        SuccessCriterion(
            id="followup-coverage",
            description="Send follow-up emails to all GHOSTED contacts",
            metric="output_contains",
            target="emails_sent",
            weight=0.3,
        ),
    ],
    constraints=[
        Constraint(
            id="real-data-only",
            description="Only report leaks found in actual HubSpot CRM data — never fabricate deals or contacts",
            constraint_type="hard",
            category="accuracy",
        ),
        Constraint(
            id="single-tool-call",
            description="Each node calls its designated tool exactly once per cycle",
            constraint_type="hard",
            category="scope",
        ),
        Constraint(
            id="halt-on-critical",
            description="Halt the monitoring loop when severity reaches critical or MAX_CYCLES of low severity elapse",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="hubspot-required",
            description="HUBSPOT_ACCESS_TOKEN is required for meaningful operation",
            constraint_type="hard",
            category="requirements",
        ),
        Constraint(
            id="email-required",
            description="GOOGLE_ACCESS_TOKEN or RESEND_API_KEY is required for sending follow-up emails",
            constraint_type="hard",
            category="requirements",
        ),
        Constraint(
            id="telegram-required",
            description="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required for sending revenue leak alerts",
            constraint_type="hard",
            category="requirements",
        ),
    ],
)

# ---- Nodes ----
# Tuples prevent accidental mutation of the module-level templates;
# RevenueLeakDetectorAgent.__init__ copies these into per-instance lists.
nodes: tuple = (monitor_node, analyze_node, notify_node, followup_node)

# ---- Edges ----
edges: tuple = (
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
)

entry_node = "monitor"
entry_points = MappingProxyType({"start": "monitor"})  # read-only at module level
terminal_nodes: tuple = ()
pause_nodes: tuple = ()


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class RevenueLeakDetectorAgent:
    """
    HubSpot Revenue Leak Detector Agent — 4-node event_loop pipeline.

    Flow: monitor -> analyze -> notify -> followup (loops until halt)

    Requires HUBSPOT_ACCESS_TOKEN to access HubSpot CRM data.
    Uses AgentRuntime for proper session management with checkpointing
    and session-isolated tool state via contextvars.
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        # Copy module-level lists/dicts so each instance has independent state
        self.nodes = list(nodes)
        self.edges = list(edges)
        self.entry_node = entry_node
        self.entry_points = dict(entry_points)
        self.pause_nodes = list(pause_nodes)
        self.terminal_nodes = list(terminal_nodes)
        self._graph: Optional[GraphSpec] = None
        self._agent_runtime: Optional[AgentRuntime] = None
        self._tool_registry: Optional[ToolRegistry] = None
        self._storage_path: Optional[Path] = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="hubspot-revenue-leak-detector-graph",
            goal_id=self.goal.id,
            version=VERSION,
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
                "You are an autonomous HubSpot revenue operations monitor. You scan the sales pipeline, "
                "detect revenue leaks, send structured alerts, and follow up with ghosted "
                "prospects. You are precise, data-driven, and escalate critical issues immediately."
            ),
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the agent runtime with tools, LLM, and session storage."""
        self._storage_path = Path.home() / ".hive" / "agents" / "hubspot_revenue_leak_detector"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        # Register tools from tools.py via TOOLS dict + tool_executor pattern
        tools_path = Path(__file__).parent / "tools.py"
        self._tool_registry.discover_from_module(tools_path)

        # Load MCP server config if present
        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        if mock_mode:
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
        # Enforce Resend as required for this agent (global spec has required=False).
        # Skipped in mock mode so maintainers can test without any credentials.
        if not mock_mode and not os.environ.get("RESEND_API_KEY"):
            try:
                from framework.credentials.storage import CompositeStorage, EncryptedFileStorage, EnvVarStorage
                from framework.credentials.store import CredentialStore
                from aden_tools.credentials import CREDENTIAL_SPECS
                spec = CREDENTIAL_SPECS.get("resend")
                if spec:
                    env_mapping = {(spec.credential_id or "resend"): spec.env_var}
                    env_storage = EnvVarStorage(env_mapping=env_mapping)
                    if os.environ.get("HIVE_CREDENTIAL_KEY"):
                        storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
                    else:
                        storage = env_storage
                    store = CredentialStore(storage=storage)
                    if not store.is_available(spec.credential_id or "resend"):
                        from framework.credentials.models import CredentialError
                        exc = CredentialError(
                            "Missing required credential: RESEND_API_KEY\n"
                            "  Required for: send_email (follow-up emails to GHOSTED contacts)\n"
                            f"  Get it at: {spec.help_url or 'https://resend.com'}"
                        )
                        exc.failed_cred_names = ["resend"]  # type: ignore[attr-defined]
                        raise exc
            except ImportError:
                pass  # aden_tools not installed, skip check
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
            timeout=timeout,
            session_state=session_state,
        )

    async def run(
        self, context: dict | None = None, mock_mode: bool = False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "start", context or {"cycle": 0}, session_state=session_state
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
        errors: List[str] = []
        warnings: List[str] = []

        node_ids = {node.id for node in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")

        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")

        for ep_id, ep_node in self.entry_points.items():
            if ep_node not in node_ids:
                errors.append(f"Entry point '{ep_id}': node '{ep_node}' not found")

        # Cross-check each node's tool list against the registered TOOLS dict.
        # Python tools (in TOOLS) must exist — errors.
        # MCP tools (registered at runtime via mcp_servers.json) — warnings only,
        # since they're not discoverable until the MCP server starts.
        try:
            from .tools import TOOLS as _TOOLS  # noqa: PLC0415
            registered_python = set(_TOOLS.keys())
            for node in self.nodes:
                for tool_name in node.tools or []:
                    if tool_name not in registered_python:
                        warnings.append(
                            f"Node '{node.id}': tool '{tool_name}' is not in local TOOLS dict "
                            f"— expected to be an MCP tool registered at runtime"
                        )
        except Exception as exc:  # pragma: no cover
            warnings.append(f"Could not validate tool references: {exc}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = RevenueLeakDetectorAgent()

__all__ = [
    "RevenueLeakDetectorAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
]
