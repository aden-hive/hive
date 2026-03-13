"""Agent graph construction for GitHub Issue Triage Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata, agent_config
from .nodes import (
    fetch_issues_node,
    triage_node,
    notify_node,
)

# Goal definition
goal = Goal(
    id="github-issue-triage",
    name="GitHub Issue Triage",
    description=(
        "Monitor a GitHub repository for open issues, automatically classify them "
        "by type, apply appropriate labels, post triage comments, and send "
        "notifications to the team via Slack or Discord."
    ),
    success_criteria=[
        SuccessCriterion(
            id="label-applied",
            description="Every triaged issue receives the correct classification label",
            metric="label_accuracy",
            target="100%",
            weight=0.35,
        ),
        SuccessCriterion(
            id="comment-posted",
            description="Every triaged issue receives a triage comment",
            metric="comment_coverage",
            target="100%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="no-duplicate-triage",
            description="Issues are not re-triaged on subsequent runs",
            metric="duplicate_rate",
            target="0%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="notification-sent",
            description="A triage summary notification is sent to Slack/Discord",
            metric="notification_delivery",
            target="sent",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="no-auto-close",
            description="Only close duplicates and invalid issues, never bugs or features",
            constraint_type="safety",
            category="scope",
        ),
        Constraint(
            id="idempotent",
            description="Re-running on already-triaged issues is a no-op",
            constraint_type="functional",
            category="reliability",
        ),
        Constraint(
            id="rate-limit-safe",
            description="Respect GitHub API rate limits via pagination and batching",
            constraint_type="functional",
            category="performance",
        ),
    ],
)

# Node list — 3-node pipeline
nodes = [
    fetch_issues_node,
    triage_node,
    notify_node,
]

# Edge definitions
edges = [
    # fetch_issues -> triage
    EdgeSpec(
        id="fetch-to-triage",
        source="fetch_issues",
        target="triage",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # triage -> notify
    EdgeSpec(
        id="triage-to-notify",
        source="triage",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # notify -> fetch_issues (loop for continuous monitoring)
    EdgeSpec(
        id="notify-to-fetch",
        source="notify",
        target="fetch_issues",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "fetch_issues"
entry_points = {"start": "fetch_issues"}
pause_nodes = []
terminal_nodes = []  # Continuous loop; stopped externally


class GitHubIssueTriageAgent:
    """
    GitHub Issue Triage Agent — 3-node pipeline for automated issue management.

    Flow: fetch_issues -> triage -> notify -> (loop)

    Security: The agent validates owner/repo at the Python layer BEFORE the LLM
    is ever invoked. If owner/repo is empty or not in allowed_repos, the run is
    aborted immediately — no GitHub API call is made.

    Uses AgentRuntime for proper session management:
    - Session-scoped storage (sessions/{session_id}/)
    - Checkpointing for resume capability
    - Runtime logging
    - Data folder for save_data/load_data (triaged_issues.json)
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.agent_config = agent_config
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

    # ------------------------------------------------------------------
    # Security: Python-layer enforcement — runs BEFORE any LLM call
    # ------------------------------------------------------------------

    def _validate_target(self, owner: str, repo: str) -> str | None:
        """Return an error string if the target is invalid, else None.

        This is the hard enforcement layer. It is pure Python and cannot be
        bypassed by any LLM hallucination.
        """
        owner = (owner or "").strip()
        repo = (repo or "").strip()

        if not owner or not repo:
            return (
                "owner and repo must both be set before running the triage agent. "
                "Edit config.py (AgentConfig.owner / AgentConfig.repo) or pass them "
                "explicitly when calling run()."
            )

        allowed = self.agent_config.allowed_repos
        if allowed and f"{owner}/{repo}" not in allowed:
            return (
                f"'{owner}/{repo}' is not in the allowed_repos list. "
                f"Add it to AgentConfig.allowed_repos in config.py to proceed. "
                f"Allowed: {allowed}"
            )

        return None

    # ------------------------------------------------------------------
    # Graph + runtime setup
    # ------------------------------------------------------------------

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="github-issue-triage-graph",
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
                "max_tool_calls_per_turn": 30,
                "max_history_tokens": 32000,
            },
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "github_issue_triage"
        storage_path.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_path

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
                id="start",
                name="Triage Repository",
                entry_node=self.entry_node,
                trigger_type="manual",
                isolation_level="shared",
            ),
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
        entry_point: str = "start",
        input_data: dict | None = None,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
        if self._agent_runtime is None:
            raise RuntimeError("Agent not started. Call start() first.")

        # Resolve owner/repo: caller-supplied values take priority over config.
        data = dict(input_data or {})
        owner = data.get("owner") or self.agent_config.owner
        repo = data.get("repo") or self.agent_config.repo

        # --- HARD SECURITY CHECK (Python layer, not LLM) ---
        err = self._validate_target(owner, repo)
        if err:
            return ExecutionResult(success=False, error=err)

        # Inject resolved + validated values and channel config.
        data["owner"] = owner
        data["repo"] = repo
        data.setdefault("slack_channel", self.agent_config.slack_channel)
        data.setdefault("discord_channel_id", self.agent_config.discord_channel_id)

        return await self._agent_runtime.trigger_and_wait(
            entry_point_id=entry_point,
            input_data=data,
            session_state=session_state,
        )

    async def run(
        self, context: dict, mock_mode=False, session_state=None
    ) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        # Validate early so CLI callers get a clear error before setup.
        owner = (context.get("owner") or self.agent_config.owner or "").strip()
        repo = (context.get("repo") or self.agent_config.repo or "").strip()
        err = self._validate_target(owner, repo)
        if err:
            return ExecutionResult(success=False, error=err)

        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self):
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
            "security": {
                "allowed_repos": self.agent_config.allowed_repos or "any (not restricted)",
                "owner_configured": bool(self.agent_config.owner),
                "repo_configured": bool(self.agent_config.repo),
            },
        }

    def validate(self):
        """Validate agent structure."""
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

        # Security warnings
        if not self.agent_config.owner:
            warnings.append(
                "AgentConfig.owner is empty — agent will refuse to run until set"
            )
        if not self.agent_config.repo:
            warnings.append(
                "AgentConfig.repo is empty — agent will refuse to run until set"
            )
        if not self.agent_config.allowed_repos:
            warnings.append(
                "AgentConfig.allowed_repos is empty — any repo can be targeted. "
                "Set this to restrict the agent to specific repositories."
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = GitHubIssueTriageAgent()
