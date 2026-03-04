"""Agent graph construction for Vercel Assistant Agent."""

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
    action_node,
    review_node,
)

goal = Goal(
    id="vercel-deployment-assistant",
    name="Vercel Deployment Assistant",
    description=(
        "Help users manage Vercel deployments, projects, and environment variables "
        "through natural language interaction with clear guidance and feedback."
    ),
    success_criteria=[
        SuccessCriterion(
            id="task-completion",
            description="User's requested Vercel operation is completed successfully",
            metric="task_success_rate",
            target="100%",
            weight=0.5,
        ),
        SuccessCriterion(
            id="user-satisfaction",
            description="User understands the results and knows what to do next",
            metric="user_satisfaction",
            target="true",
            weight=0.3,
        ),
        SuccessCriterion(
            id="error-handling",
            description="Errors are explained clearly with actionable solutions",
            metric="error_clarity",
            target="100%",
            weight=0.2,
        ),
    ],
    constraints=[
        Constraint(
            id="credential-guidance",
            description="Provide clear instructions for setting up Vercel credentials",
            constraint_type="functional",
            category="usability",
        ),
        Constraint(
            id="safe-operations",
            description="Only perform operations explicitly requested by the user",
            constraint_type="security",
            category="safety",
        ),
    ],
)

nodes = [
    intake_node,
    action_node,
    review_node,
]

edges = [
    EdgeSpec(
        id="intake-to-action",
        source="intake",
        target="action",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="action-to-review",
        source="action",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-to-intake",
        source="review",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(next_action).lower() == 'new_task'",
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []

identity_prompt = """\
You are a Vercel deployment assistant. You help users manage their Vercel deployments,
projects, and environment variables through natural language commands.

You can:
- List Vercel projects
- Create new deployments
- Check deployment status
- Set environment variables

Always be helpful, clear, and guide users through the process step by step.
"""


class VercelAssistant:
    """Vercel Assistant Agent for deployment management."""

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
        """Build the agent graph."""
        return GraphSpec(
            id="vercel-assistant-graph",
            goal_id=goal.id,
            version="1.0.0",
            entry_node=entry_node,
            entry_points=entry_points,
            terminal_nodes=terminal_nodes,
            pause_nodes=pause_nodes,
            nodes=nodes,
            edges=edges,
            identity_prompt=identity_prompt,
            max_steps=self.config.max_steps,
            max_retries_per_node=self.config.max_retries,
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        self._storage_path = Path.home() / ".hive" / "agents" / "vercel_assistant"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

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
        """Validate the agent structure."""
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

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


default_agent = VercelAssistant()
