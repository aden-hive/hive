"""Agent graph construction for Hacker News Briefing Agent."""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    collect_hn_candidates_node,
    deliver_briefing_node,
    intake_preferences_node,
    rank_and_summarize_node,
    review_briefing_node,
)

goal = Goal(
    id="daily-hn-briefing",
    name="Daily Hacker News Briefing Agent",
    description=(
        "Produce a daily Hacker News briefing by collecting top stories, ranking and "
        "summarizing them, and delivering the output in user-selected channels."
    ),
    success_criteria=[
        SuccessCriterion(
            id="collect-candidate-stories",
            description=(
                "Collect candidate stories from Hacker News and linked pages with "
                "valid URLs and metadata."
            ),
            metric="story_collection_success_rate",
            target=">=0.9",
            weight=0.25,
        ),
        SuccessCriterion(
            id="produce-concise-briefing",
            description=(
                "Produce a concise briefing with prioritized items and why-it-matters "
                "notes."
            ),
            metric="briefing_quality_check",
            target="pass",
            weight=0.3,
        ),
        SuccessCriterion(
            id="respect-runtime-preferences",
            description="Respect runtime preferences for channels and briefing config.",
            metric="preference_adherence_rate",
            target="1.0",
            weight=0.2,
        ),
        SuccessCriterion(
            id="deliver-selected-channels",
            description="Deliver output in selected channel(s) with stable structure.",
            metric="delivery_success_rate",
            target=">=0.95",
            weight=0.15,
        ),
        SuccessCriterion(
            id="complete-within-runtime-budget",
            description="Complete end-to-end run within practical daily budget.",
            metric="run_duration_minutes",
            target="<5",
            weight=0.1,
        ),
    ],
    constraints=[
        Constraint(
            id="no-fabricated-sources",
            description="Every briefing item must include a source link.",
            constraint_type="must",
            category="quality",
        ),
        Constraint(
            id="graceful-partial-failure",
            description=(
                "If some fetch steps fail, still produce a usable briefing and report "
                "missing items."
            ),
            constraint_type="must",
            category="reliability",
        ),
        Constraint(
            id="no-destructive-actions",
            description="Only read/process/publish workflow outputs.",
            constraint_type="must_not",
            category="safety",
        ),
        Constraint(
            id="runtime-configurable",
            description="Timezone and channels are runtime-configurable.",
            constraint_type="must",
            category="configurability",
        ),
    ],
)

nodes = [
    intake_preferences_node,
    collect_hn_candidates_node,
    rank_and_summarize_node,
    review_briefing_node,
    deliver_briefing_node,
]

edges = [
    EdgeSpec(
        id="intake-preferences-to-collect-hn-candidates",
        source="intake-preferences",
        target="collect-hn-candidates",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="collect-hn-candidates-to-rank-and-summarize",
        source="collect-hn-candidates",
        target="rank-and-summarize",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="rank-and-summarize-to-review-briefing",
        source="rank-and-summarize",
        target="review-briefing",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-briefing-to-deliver-briefing",
        source="review-briefing",
        target="deliver-briefing",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved_briefing is not None",
        priority=1,
    ),
    EdgeSpec(
        id="review-briefing-to-rank-and-summarize-feedback",
        source="review-briefing",
        target="rank-and-summarize",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="review_feedback is not None",
        priority=-1,
    ),
]

entry_node = "intake-preferences"
entry_points = {"start": "intake-preferences"}
pause_nodes = []
terminal_nodes = ["deliver-briefing"]


class HackerNewsBriefingAgent:
    """Hacker News briefing pipeline with review loop."""

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
        return GraphSpec(
            id="hacker-news-briefing-graph",
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
            conversation_mode="continuous",
            identity_prompt=(
                "You are a Hacker News briefing assistant. You prioritize accuracy, "
                "brevity, and citations. Do not fabricate sources."
            ),
        )

    def _setup(self, mock_mode=False) -> None:
        self._storage_path = Path.home() / ".hive" / "agents" / "hacker_news_briefing"
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
            )

        self._graph = self._build_graph()
        checkpoint_config = CheckpointConfig(
            enabled=True,
            checkpoint_on_node_start=False,
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=7,
            async_checkpoint=True,
        )

        runtime = create_agent_runtime(
            graph=self._graph,
            goal=self.goal,
            storage_path=self._storage_path,
            entry_points=[
                EntryPointSpec(
                    id="start",
                    name="Start Briefing",
                    entry_node=self.entry_node,
                    trigger_type="manual",
                    isolation_level="shared",
                )
            ],
            llm=llm,
            tools=list(self._tool_registry.get_tools().values()),
            tool_executor=self._tool_registry.get_executor(),
            checkpoint_config=checkpoint_config,
        )
        self._agent_runtime = runtime

    async def start(self, mock_mode=False) -> None:
        if self._agent_runtime is None:
            self._setup(mock_mode=mock_mode)
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
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
        await self.start(mock_mode=mock_mode)
        try:
            result = await self.trigger_and_wait(
                "start", context, session_state=session_state
            )
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

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = HackerNewsBriefingAgent()
