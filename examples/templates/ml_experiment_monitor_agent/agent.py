"""Agent graph construction for the ML Experiment Monitor Agent.

Flow: query_experiments -> evaluate_results -> send_alert

The agent fetches recent MLflow runs, identifies any where
metrics.accuracy < threshold, then posts a Slack message with the
failing run details — or an all-clear if every run passes.
"""

import asyncio
from typing import Any, TYPE_CHECKING

from framework.orchestrator import (
    Constraint,
    EdgeCondition,
    EdgeSpec,
    Goal,
    NodeSpec,
    SuccessCriterion,
)
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.orchestrator import ExecutionResult, Orchestrator
from framework.host.event_bus import EventBus
from framework.tracker.decision_tracker import DecisionTracker as Runtime
from framework.llm import LiteLLMProvider
from framework.loader.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from framework.config import RuntimeConfig

# ---------------------------------------------------------------------------
# Default runtime configuration
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = 4096


class AgentConfig:
    """Runtime configuration for the ML Experiment Monitor."""

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key
        self.api_base = api_base


default_config = AgentConfig()

metadata = type(
    "Metadata",
    (),
    {
        "name": "ML Experiment Monitor",
        "version": "1.0.0",
        "description": (
            "Monitors MLflow experiments for accuracy regressions and "
            "sends a Slack alert with the failing run details."
        ),
    },
)()

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

goal: Goal = Goal(
    id="ml-experiment-monitor",
    name="ML Experiment Monitor",
    description=(
        "Monitor a set of MLflow experiments, identify runs where accuracy "
        "dropped below a configurable threshold, and send a Slack alert with "
        "the run details — or an all-clear message when all runs pass."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-runs-fetched",
            description="Recent runs are successfully retrieved from the MLflow tracking server",
            metric="runs_fetched",
            target="true",
            weight=0.33,
        ),
        SuccessCriterion(
            id="sc-threshold-evaluated",
            description="Each run's accuracy is compared against the configured threshold",
            metric="threshold_evaluated",
            target="true",
            weight=0.33,
        ),
        SuccessCriterion(
            id="sc-slack-sent",
            description="A Slack message is sent regardless of whether any runs failed",
            metric="slack_sent",
            target="true",
            weight=0.34,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-fabrication",
            description="Only report runs and metrics that actually exist in MLflow",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-always-notify",
            description="Always send a Slack message — either an alert or an all-clear",
            constraint_type="hard",
            category="behavior",
        ),
    ],
)

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

_QUERY_SYSTEM_PROMPT = """You are an ML monitoring agent. Your job in this step is to retrieve
recent runs from the MLflow experiment specified in the input.

Call `mlflow_list_runs` with the provided experiment_id. Use the `max_results` input value
(default 50 if not provided). Store the returned runs list as your output."""

_EVALUATE_SYSTEM_PROMPT = """You are an ML monitoring agent. Your job is to analyse the runs
returned from MLflow and identify any that have accuracy below the threshold.

For each run in the `runs` list:
- Extract metrics.accuracy (treat missing accuracy as 0.0)
- Compare to `accuracy_threshold` (default 0.8 if not provided)
- Collect failing runs with their run_id, run_name, accuracy, and status

Produce:
- `alert_needed` (bool): True if any run has accuracy < threshold
- `summary` (str): A concise message.
  * If alert_needed is True: list each failing run with its run_id, name, accuracy, and status.
  * If alert_needed is False: write a brief all-clear message noting how many runs passed."""

_ALERT_SYSTEM_PROMPT = """You are an ML monitoring agent. Your job is to send a Slack message
to the channel specified in `slack_channel`.

If `alert_needed` is True, prefix the message with ":rotating_light: *MLflow Alert*" and
send the `summary` as the message body so the team can act immediately.

If `alert_needed` is False, prefix with ":white_check_mark: *MLflow OK*" and send the
all-clear summary.

Call `slack_send_message` with the channel and the formatted message.
Set `notification_status` to "sent" after the tool succeeds."""

query_experiments_node = NodeSpec(
    id="query_experiments",
    name="Query Experiments",
    description="Fetch recent runs from the configured MLflow experiment",
    node_type="event_loop",
    input_keys=["experiment_id", "max_results"],
    output_keys=["runs"],
    nullable_output_keys=[],
    system_prompt=_QUERY_SYSTEM_PROMPT,
    tools=["mlflow_list_runs"],
    client_facing=False,
)

evaluate_results_node = NodeSpec(
    id="evaluate_results",
    name="Evaluate Results",
    description="Compare each run's accuracy against the threshold and summarise failures",
    node_type="event_loop",
    input_keys=["runs", "accuracy_threshold"],
    output_keys=["alert_needed", "summary"],
    nullable_output_keys=[],
    system_prompt=_EVALUATE_SYSTEM_PROMPT,
    tools=[],
    client_facing=False,
)

send_alert_node = NodeSpec(
    id="send_alert",
    name="Send Alert",
    description="Post the summary to Slack — alert or all-clear depending on evaluation",
    node_type="event_loop",
    input_keys=["summary", "alert_needed", "slack_channel"],
    output_keys=["notification_status"],
    nullable_output_keys=[],
    system_prompt=_ALERT_SYSTEM_PROMPT,
    tools=["slack_send_message"],
    client_facing=True,
)

nodes: list[NodeSpec] = [
    query_experiments_node,
    evaluate_results_node,
    send_alert_node,
]

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

edges: list[EdgeSpec] = [
    EdgeSpec(
        id="query-to-evaluate",
        source="query_experiments",
        target="evaluate_results",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="evaluate-to-alert",
        source="evaluate_results",
        target="send_alert",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node: str = "query_experiments"
entry_points: dict[str, str] = {"start": "query_experiments"}
pause_nodes: list[str] = []
terminal_nodes: list[str] = ["send_alert"]

# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class MLExperimentMonitorAgent:
    """
    ML Experiment Monitor — 3-node pipeline.

    Flow: query_experiments -> evaluate_results -> send_alert

    Input context keys:
        experiment_id (str): MLflow experiment ID to monitor.
        accuracy_threshold (float): Minimum acceptable accuracy (default 0.8).
        max_results (int): Maximum runs to fetch per poll (default 50).
        slack_channel (str): Slack channel name or ID for notifications.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        """
        Initialise the ML Experiment Monitor Agent.

        Args:
            config: Optional runtime configuration. Defaults to default_config.
        """
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.entry_points = entry_points
        self.pause_nodes = pause_nodes
        self.terminal_nodes = terminal_nodes
        self._executor: Orchestrator | None = None
        self._graph: GraphSpec | None = None
        self._event_bus: EventBus | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """
        Build the GraphSpec for the ML experiment monitoring workflow.

        Returns:
            A GraphSpec defining the 3-node pipeline.
        """
        return GraphSpec(
            id="ml-experiment-monitor-graph",
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
                "max_iterations": 30,
                "max_tool_calls_per_turn": 10,
                "max_history_tokens": 16000,
            },
        )

    def _setup(self) -> Orchestrator:
        """
        Initialise the executor with LLM, tools, and event bus.

        Returns:
            An initialised Orchestrator instance.
        """
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "agents" / "ml_experiment_monitor_agent"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if not mcp_config_path.exists():
            raise RuntimeError(
                f"mcp_servers.json not found at {mcp_config_path}. "
                "Copy the template and create the file before running the agent."
            )
        try:
            self._tool_registry.load_mcp_config(mcp_config_path)
        except Exception as exc:
            raise RuntimeError(f"Failed to load MCP tool configuration: {exc}") from exc

        required_tools = {"mlflow_list_runs", "slack_send_message"}
        registered = set(self._tool_registry.get_tools().keys())
        missing = required_tools - registered
        if missing:
            raise RuntimeError(
                f"Required tools not registered after loading mcp_servers.json: {sorted(missing)}. "
                "Ensure the MCP server exposes these tools."
            )

        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()
        runtime = Runtime(storage_path)

        self._executor = Orchestrator(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            event_bus=self._event_bus,
            storage_path=storage_path,
            loop_config=self._graph.loop_config,
        )

        return self._executor

    async def start(self) -> None:
        """Set up the agent (initialise executor and tools)."""
        if self._executor is None:
            self._setup()

    async def stop(self) -> None:
        """Clean up resources."""
        self._executor = None
        self._event_bus = None

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """
        Execute the graph and wait for completion.

        Args:
            entry_point: The graph entry point to trigger.
            input_data: Data to pass to the entry node.
            timeout: Optional execution timeout in seconds.
            session_state: Optional initial session state.

        Returns:
            The execution result, or None if execution timed out.
        """
        if self._executor is None:
            raise RuntimeError("Agent not started. Call start() first.")
        if self._graph is None:
            raise RuntimeError("Graph not built. Call start() first.")
        if entry_point not in self.entry_points:
            valid = list(self.entry_points.keys())
            raise ValueError(f"Unknown entry_point {entry_point!r}. Valid options: {valid}")

        coro = self._executor.execute(
            graph=self._graph,
            goal=self.goal,
            input_data=input_data,
            session_state=session_state,
        )
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    async def run(
        self,
        context: dict[str, Any],
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Run the agent (convenience wrapper for a single execution).

        Args:
            context: Input context for the agent. Expected keys:
                - experiment_id (str): MLflow experiment ID.
                - accuracy_threshold (float): Minimum acceptable accuracy.
                - max_results (int): Max runs to fetch (default 50).
                - slack_channel (str): Slack channel for notifications.
            session_state: Optional initial session state.

        Returns:
            The final execution result.
        """
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> dict[str, Any]:
        """Get agent metadata for introspection."""
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

    def validate(self) -> dict[str, Any]:
        """
        Validate agent structure for cycles, missing nodes, or invalid edges.

        Returns:
            Dict with 'valid' (bool), 'errors' (list), and 'warnings' (list).
        """
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

        for terminal in self.terminal_nodes:
            if terminal not in node_ids:
                errors.append(f"Terminal node '{terminal}' not found")

        for ep_id, node_id in self.entry_points.items():
            if node_id not in node_ids:
                errors.append(f"Entry point '{ep_id}' references unknown node '{node_id}'")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# Create default instance
default_agent: MLExperimentMonitorAgent = MLExperimentMonitorAgent()
