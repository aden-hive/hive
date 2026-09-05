"""xAPI Learning Record Agent — deterministic 5-node LRS pipeline.

Architecture:
    event-capture → statement-builder → validator → lrs-dispatch → confirmation

All nodes except event-capture and confirmation are non-client-facing and
run deterministically via tool calls (no LLM reasoning required for the
statement-builder, validator, and lrs-dispatch nodes).

This agent can operate as a standalone LRS sidecar alongside the
Curriculum Research Agent (#5301) and Document Intelligence A2A (#5523)
to record learning interactions as xAPI statements in real time.
"""

import logging
from pathlib import Path

from framework.orchestrator import (
    Constraint,
    EdgeCondition,
    EdgeSpec,
    ExecutionResult,
    Goal,
    GraphSpec,
    SuccessCriterion,
)
from framework.orchestrator.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.loader.tool_registry import ToolRegistry
from framework.host.agent_host import AgentHost
from framework.host.execution_manager import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    confirmation_node,
    event_capture_node,
    lrs_dispatch_node,
    statement_builder_node,
    validator_node,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

goal = Goal(
    id="xapi-learning-record",
    name="xAPI Learning Record",
    description=(
        "Capture a learning event, build a valid xAPI 1.0.3 statement, "
        "validate its structure, dispatch it to an LRS, and confirm success."
    ),
    success_criteria=[
        SuccessCriterion(
            id="valid-statement",
            description="xAPI 1.0.3 statement passes all structural validation checks",
            metric="statement_valid",
            target="true",
            weight=0.35,
        ),
        SuccessCriterion(
            id="lrs-accepted",
            description="LRS returns HTTP 200 or 204 accepting the statement",
            metric="lrs_accepted",
            target="true",
            weight=0.50,
        ),
        SuccessCriterion(
            id="confirmation-returned",
            description="statement_id and timestamp returned to the caller",
            metric="confirmation_complete",
            target="true",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="xapi-1.0.3",
            description="All statements must conform to xAPI specification version 1.0.3",
            constraint_type="hard",
            category="compliance",
        ),
        Constraint(
            id="no-fabrication",
            description=(
                "The agent must never invent or infer actor, verb, or object fields. "
                "If required fields are missing, validation must fail explicitly."
            ),
            constraint_type="hard",
            category="data-integrity",
        ),
        Constraint(
            id="no-auto-retry-on-4xx",
            description=(
                "4xx LRS errors (e.g. 400 Bad Request, 401 Unauthorized) must be "
                "reported immediately without retry — they indicate config or data errors."
            ),
            constraint_type="hard",
            category="operational",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Node list
# ---------------------------------------------------------------------------

nodes = [
    event_capture_node,
    statement_builder_node,
    validator_node,
    lrs_dispatch_node,
    confirmation_node,
]


# ---------------------------------------------------------------------------
# Edges (linear pipeline)
# ---------------------------------------------------------------------------

edges = [
    EdgeSpec(
        id="capture-to-builder",
        source="event-capture",
        target="statement-builder",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="builder-to-validator",
        source="statement-builder",
        target="validator",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="validator-to-dispatch",
        source="validator",
        target="lrs-dispatch",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="dispatch-to-confirmation",
        source="lrs-dispatch",
        target="confirmation",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="confirmation-to-capture",
        source="confirmation",
        target="event-capture",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]


# ---------------------------------------------------------------------------
# Graph configuration
# ---------------------------------------------------------------------------

entry_node = "event-capture"
entry_points = {"default": "event-capture"}
async_entry_points: list = []
pause_nodes: list[str] = []
terminal_nodes: list[str] = []

loop_config = {
    "max_iterations": 50,
    "max_tool_calls_per_turn": 10,
    "max_tool_result_chars": 4000,
    "max_history_tokens": 16000,
}

conversation_mode = "continuous"

identity_prompt = (
    "You are an xAPI Learning Record Agent. "
    "You capture learning events, build valid xAPI 1.0.3 statements, "
    "validate their structure, dispatch them to an LRS, and confirm success. "
    "The pipeline is deterministic — statement building, validation, and LRS "
    "dispatch are handled by pure-function tools, not LLM reasoning."
)


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class XAPILearningRecordAgent:
    """xAPI Learning Record Agent — 5-node deterministic LRS pipeline.

    Flow:
        event-capture -> statement-builder -> validator
        -> lrs-dispatch -> confirmation -> event-capture (loop)

    Pipeline:
    1. event-capture:     Collect and normalize the learning event from the user
    2. statement-builder: Build xAPI 1.0.3 statement via build_xapi_statement tool
    3. validator:         Validate via validate_statement tool (no LLM)
    4. lrs-dispatch:      POST to LRS via post_to_lrs tool, retry once on 5xx
    5. confirmation:      Report statement_id, timestamp, success/error to user

    No LLM inference is required for nodes 2-4. The agent can be embedded
    as a sidecar alongside Curriculum Research Agent (#5301) and Document
    Intelligence A2A (#5523) to record learning interactions as xAPI statements.
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
        self._agent_host: AgentHost | None = None
        self._graph: GraphSpec | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec for the pipeline."""
        return GraphSpec(
            id="xapi-learning-record-graph",
            goal_id=self.goal.id,
            version="0.1.0",
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

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up runtime, tool registry, LLM provider, and checkpointing."""
        self._storage_path = (
            Path.home() / ".hive" / "agents" / "xapi_learning_record"
        )
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

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
            ),
        ]

        self._agent_host = AgentHost(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=entry_point_specs,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=checkpoint_config,
        )

    async def start(self, mock_mode: bool = False) -> None:
        """Set up and start the agent runtime."""
        if self._agent_host is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_host.is_running:
            await self._agent_host.start()

    async def stop(self) -> None:
        """Stop the agent runtime and clean up."""
        if self._agent_host and self._agent_host.is_running:
            await self._agent_host.stop()
        self._agent_host = None

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the pipeline and wait for completion."""
        if self._agent_host is None:
            raise RuntimeError("Agent not started. Call start() first.")

        return await self._agent_host.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data,
            timeout=timeout,
            session_state=session_state,
        )

    async def run(
        self,
        context: dict,
        mock_mode: bool = False,
        session_state: dict | None = None,
    ) -> ExecutionResult:
        """Run the agent pipeline (convenience method for single execution)."""
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> dict:
        """Return agent information dict."""
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
        """Validate agent graph structure (node/edge consistency)."""
        errors: list[str] = []
        warnings: list[str] = []

        node_ids = {node.id for node in self.nodes}

        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(
                    f"Edge '{edge.id}': source '{edge.source}' not found in nodes"
                )
            if edge.target not in node_ids:
                errors.append(
                    f"Edge '{edge.id}': target '{edge.target}' not found in nodes"
                )

        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found in nodes")

        for terminal in self.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node '{terminal}' not found in nodes")

        for ep_id, node_id in self.entry_points.items():
            if node_id not in node_ids:
                errors.append(
                    f"Entry point '{ep_id}' references unknown node '{node_id}'"
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# ---------------------------------------------------------------------------
# Default instance
# ---------------------------------------------------------------------------

default_agent = XAPILearningRecordAgent()
