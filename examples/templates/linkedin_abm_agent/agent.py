"""Agent graph construction for LinkedIn ABM Agent."""

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
    prospect_node,
    enrich_node,
    message_node,
    review_node,
    outreach_node,
    tracking_node,
)

goal = Goal(
    id="linkedin-abm-agent",
    name="LinkedIn ABM Agent",
    description=(
        "Execute multi-channel Account-Based Marketing campaigns. "
        "Prospect LinkedIn leads, enrich with Apollo.io and Skip Trace, "
        "generate personalized messages, get human approval, and execute "
        "coordinated outreach via email, LinkedIn, and direct mail."
    ),
    success_criteria=[
        SuccessCriterion(
            id="prospects-enriched",
            description="All prospects enriched with contact data (email, phone, address)",
            metric="enrichment_rate",
            target=">=80%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="messages-personalized",
            description="All messages personalized with prospect-specific data",
            metric="personalization_rate",
            target="100%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="human-approval",
            description="User reviews and approves campaign before sending",
            metric="user_approval",
            target="true",
            weight=0.25,
        ),
        SuccessCriterion(
            id="outreach-executed",
            description="All approved outreach executed across channels",
            metric="outreach_completion",
            target=">=95%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="campaign-tracked",
            description="Campaign logged and report exported",
            metric="tracking_complete",
            target="true",
            weight=0.10,
        ),
    ],
    constraints=[
        Constraint(
            id="human-approval-required",
            description="Never send outreach without explicit human approval",
            constraint_type="hard",
            category="safety",
        ),
        Constraint(
            id="respect-opt-outs",
            description="Skip prospects who have opted out or bounced previously",
            constraint_type="hard",
            category="compliance",
        ),
        Constraint(
            id="rate-limiting",
            description="Respect API rate limits for LinkedIn, Apollo, and Scribeless",
            constraint_type="soft",
            category="technical",
        ),
        Constraint(
            id="data-privacy",
            description="Do not store sensitive data longer than necessary",
            constraint_type="soft",
            category="compliance",
        ),
    ],
)

nodes = [
    intake_node,
    prospect_node,
    enrich_node,
    message_node,
    review_node,
    outreach_node,
    tracking_node,
]

edges = [
    EdgeSpec(
        id="intake-to-prospect",
        source="intake",
        target="prospect",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="prospect-to-enrich",
        source="prospect",
        target="enrich",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="enrich-to-message",
        source="enrich",
        target="message",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="message-to-review",
        source="message",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="review-to-message",
        source="review",
        target="message",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == False",
        priority=1,
    ),
    EdgeSpec(
        id="review-to-outreach",
        source="review",
        target="outreach",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == True",
        priority=2,
    ),
    EdgeSpec(
        id="outreach-to-tracking",
        source="outreach",
        target="tracking",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="tracking-to-intake",
        source="tracking",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []

conversation_mode = "continuous"
identity_prompt = (
    "You are the LinkedIn ABM Agent, a multi-channel outreach automation specialist. "
    "You help sales and marketing teams execute Account-Based Marketing campaigns "
    "across LinkedIn, email, and direct mail. You are precise, thorough, and always "
    "get human approval before sending. No emojis."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class LinkedInABMAgent:
    """
    LinkedIn ABM Agent — Multi-Channel Outbound Automation.

    Flow: intake -> prospect -> enrich -> message -> review -> outreach -> tracking
                                                          |
                                                          +-- feedback loop (if not approved)

    Features:
    - LinkedIn profile scraping
    - Apollo.io enrichment (email, phone)
    - Skip Trace for mailing addresses
    - Personalized message generation
    - Human-in-the-loop approval
    - Multi-channel execution (email, LinkedIn, direct mail)
    - Campaign tracking and reporting
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
            id="linkedin-abm-agent-graph",
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
            conversation_mode=conversation_mode,
            identity_prompt=identity_prompt,
        )

    def _setup(self, mock_mode: bool = False) -> None:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "linkedin_abm_agent"
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

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


default_agent = LinkedInABMAgent()
