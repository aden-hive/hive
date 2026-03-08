"""Agent graph construction for SocialStake Agent."""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import AsyncEntryPointSpec, GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    daily_checkin_node,
    intake_node,
    notify_node,
    settle_stake_node,
    stake_setup_node,
    update_progress_node,
    verify_proof_node,
)

goal = Goal(
    id="social-stake-goal",
    name="SocialStake - AI-Governed Financial Accountability",
    description=(
        "An AI-governed financial accountability protocol that helps users improve social skills "
        "by staking USDC. The AI Arbiter verifies real-world social interactions through various "
        "proof methods (photos, meeting reports, calendar events, videos) and releases funds "
        "based on verified progress toward the user's social goals."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-goal-collection",
            description=(
                "Accurately collects user's social goal, stake amount, and commitment period"
            ),
            metric="intake_completeness",
            target="100%",
            weight=0.1,
        ),
        SuccessCriterion(
            id="sc-stake-setup",
            description="Successfully initializes stake on-chain with correct parameters",
            metric="stake_initialization_rate",
            target="100%",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-daily-engagement",
            description="Maintains user engagement through daily check-ins and reminders",
            metric="checkin_response_rate",
            target=">=80%",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-verification-accuracy",
            description="Accurately verifies submitted proofs with appropriate confidence scores",
            metric="verification_accuracy",
            target=">=0.85",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-fair-settlement",
            description="Executes fair stake settlement based on actual progress achieved",
            metric="settlement_fairness",
            target="100%",
            weight=0.3,
        ),
    ],
    constraints=[
        Constraint(
            id="c-fund-safety",
            description=(
                "User funds must be handled securely; stake can only be released based on "
                "verified progress, never arbitrarily"
            ),
            constraint_type="hard",
            category="security",
        ),
        Constraint(
            id="c-verification-integrity",
            description=(
                "All proofs must be verified objectively; no verification should be biased "
                "or manipulated"
            ),
            constraint_type="hard",
            category="integrity",
        ),
        Constraint(
            id="c-user-privacy",
            description=(
                "User's personal information, photos, and interaction details must be "
                "handled with privacy and not shared externally"
            ),
            constraint_type="ethical",
            category="privacy",
        ),
        Constraint(
            id="c-motivation-support",
            description=(
                "Agent must maintain a supportive and encouraging tone; never shame users "
                "for missed goals"
            ),
            constraint_type="behavioral",
            category="user_experience",
        ),
        Constraint(
            id="c-minimum-stake",
            description="Minimum stake amount is 10 USDC to ensure meaningful commitment",
            constraint_type="hard",
            category="financial",
        ),
    ],
)

nodes = [
    intake_node,
    stake_setup_node,
    daily_checkin_node,
    verify_proof_node,
    update_progress_node,
    settle_stake_node,
    notify_node,
]

edges = [
    EdgeSpec(
        id="intake-to-stake-setup",
        source="intake",
        target="stake-setup",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="stake-setup-to-notify",
        source="stake-setup",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="notify-to-daily-checkin",
        source="notify",
        target="daily-checkin",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="daily-checkin-to-verify",
        source="daily-checkin",
        target="verify-proof",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="proof_submitted == True",
        priority=1,
    ),
    EdgeSpec(
        id="daily-checkin-loop",
        source="daily-checkin",
        target="daily-checkin",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="proof_submitted == False and days_remaining > 0",
        priority=2,
    ),
    EdgeSpec(
        id="verify-to-update-progress",
        source="verify-proof",
        target="update-progress",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="update-progress-to-notify",
        source="update-progress",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="notify-to-daily-checkin-continue",
        source="notify",
        target="daily-checkin",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="days_remaining > 0",
        priority=1,
    ),
    EdgeSpec(
        id="notify-to-settle",
        source="notify",
        target="settle-stake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="days_remaining <= 0",
        priority=2,
    ),
    EdgeSpec(
        id="settle-to-notify-final",
        source="settle-stake",
        target="notify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="notify-to-intake-restart",
        source="notify",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="settlement_status == 'settled'",
        priority=3,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
async_entry_points = [
    AsyncEntryPointSpec(
        id="daily-timer",
        name="Daily Check-in Timer",
        entry_node="daily-checkin",
        trigger_type="timer",
        trigger_config={"interval_minutes": 1440},
        isolation_level="shared",
        max_concurrent=1,
    ),
]
pause_nodes = []
terminal_nodes = []

conversation_mode = "continuous"
identity_prompt = (
    "You are SocialStake, an AI-governed financial accountability protocol. "
    "You help users improve their social skills by staking USDC that only you, "
    "the AI Arbiter, can release based on verified real-world interactions. "
    "You provide daily motivation, verify proof submissions, and fairly settle stakes."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class SocialStakeAgent:
    """
    SocialStake Agent - AI-governed financial accountability for social improvement.

    Flow: intake -> stake-setup -> notify -> daily-checkin (loop) -> verify-proof ->
           update-progress -> notify -> (daily-checkin or settle-stake) -> notify -> intake

    Uses AgentRuntime for:
    - Multi-entry-point execution (primary + timer-driven daily check-ins)
    - Session-scoped storage for stake tracking
    - Shared state for progress persistence
    - Checkpointing for resume capability
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
        self._graph = None
        self._agent_runtime = None
        self._tool_registry = None
        self._storage_path = None

    def _build_graph(self):
        return GraphSpec(
            id="social-stake-graph",
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
            async_entry_points=async_entry_points,
        )

    def _setup(self):
        self._storage_path = Path.home() / ".hive" / "agents" / "social_stake"
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

        checkpoint_config = CheckpointConfig(
            enabled=True,
            checkpoint_on_node_complete=True,
            checkpoint_max_age_days=30,
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
            EntryPointSpec(
                id="daily-timer",
                name="Daily Check-in Timer",
                entry_node="daily-checkin",
                trigger_type="timer",
                trigger_config={"interval_minutes": 1440},
                isolation_level="shared",
                max_concurrent=1,
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
                "default", context, session_state=session_state
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
            "async_entry_points": [
                {"id": ep.id, "name": ep.name, "entry_node": ep.entry_node}
                for ep in async_entry_points
            ],
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
        for ep in async_entry_points:
            if ep.entry_node not in node_ids:
                errors.append(
                    f"Async entry point '{ep.id}' references unknown node '{ep.entry_node}'"
                )
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = SocialStakeAgent()
