"""Agent graph construction for Release Notes Generator Agent."""

from pathlib import Path
from typing import Any

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
    collect_changes_node,
    classify_changes_node,
    generate_notes_node,
)

# Goal definition
goal = Goal(
    id="release-notes-generation",
    name="Release Notes Generation",
    description="Generate structured release notes from GitHub repository commits.",
    success_criteria=[
        SuccessCriterion(
            id="credential-validation",
            description="Successfully validate GitHub credentials before fetching data",
            metric="credential_success_rate",
            target="100%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="data-collection",
            description="Successfully fetch recent commits from the specified repository",
            metric="commit_fetch_success",
            target="100%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="classification-accuracy",
            description="Accurately classify commits into Features, Bug Fixes, Improvements, Breaking Changes",
            metric="classification_precision",
            target=">=0.85",
            weight=0.30,
        ),
        SuccessCriterion(
            id="output-quality",
            description="Generated release notes follow the correct format and include all relevant changes",
            metric="format_compliance",
            target="100%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="github-credentials-required",
            description="GitHub Personal Access Token must be configured before the agent can fetch commits",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="repository-access",
            description="User must have access to the specified GitHub repository",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="valid-repo-format",
            description="Repository must be specified in owner/repo format",
            constraint_type="hard",
            category="functional",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    collect_changes_node,
    classify_changes_node,
    generate_notes_node,
]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-collect",
        source="intake",
        target="collect_changes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="collect-to-classify",
        source="collect_changes",
        target="classify_changes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-generate",
        source="classify_changes",
        target="generate_notes",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["generate_notes"]

# Module-level vars read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = "You are a release notes generator assistant. You help developers automatically create structured release notes from GitHub repository commits."
loop_config = {
    "max_iterations": 50,
    "max_tool_calls_per_turn": 10,
    "max_history_tokens": 16000,
}


class ReleaseNotesGeneratorAgent:
    """
    Release Notes Generator Agent — 4-node pipeline for generating release notes from GitHub commits.
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
            id="release-notes-generator-graph",
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
        self._storage_path = Path.home() / ".hive" / "agents" / "release_notes_generator"
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        llm = None
        if not mock_mode:
            llm = LiteLLMProvider(
                model=self.config.model,
                api_key=self.config.api_key,
                api_base=self.config.api_base,
                temperature=self.config.temperature,
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
        """Set up and start the agent runtime."""
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self):
        """Stop the agent runtime and clean up."""
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
        """Trigger an entry point and wait for completion."""
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")
        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=input_data or {},
            session_state=session_state,
        )

    async def run(self, context, session_state=None):
        """Run the agent with the given context."""
        await self.start()
        try:
            result = await self.trigger_and_wait(
                "default", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> dict[str, Any]:
        """Get agent information."""
        return {
            "id": "release-notes-generator",
            "name": metadata.name,
            "version": metadata.version,
            "description": metadata.description,
            "goal": self.goal.description,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
        }

    def validate(self) -> dict[str, Any]:
        """Validate the agent configuration."""
        errors = []

        # Check nodes
        node_ids = {node.id for node in self.nodes}
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")

        # Check terminal nodes
        for terminal_node in self.terminal_nodes:
            if terminal_node not in node_ids:
                errors.append(f"Terminal node '{terminal_node}' not found")

        # Check edges refer to valid nodes
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge target '{edge.target}' not found")

        return {"valid": len(errors) == 0, "errors": errors}


# Create default instance
default_agent = ReleaseNotesGeneratorAgent()
