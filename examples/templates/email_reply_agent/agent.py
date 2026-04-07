"""Agent graph construction for Email Reply Agent."""

from pathlib import Path

from framework.orchestrator import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.orchestrator import ExecutionResult
from framework.orchestrator.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.loader.tool_registry import ToolRegistry
from framework.host.agent_host import create_agent_runtime
from framework.host.execution_manager import EntryPointSpec

from .config import default_config, metadata
from .nodes import intake_node, search_node, confirm_draft_node

# Goal definition
goal = Goal(
    id="email-reply-goal",
    name="Email Reply Agent",
    description="Filter unreplied emails by user criteria, confirm recipients, send personalized replies.",
    success_criteria=[
        SuccessCriterion(
            id="sc-filter",
            description="Accurately finds unreplied emails matching user criteria",
            metric="Precision of email filtering",
            target="90%",
            weight=0.35,
        ),
        SuccessCriterion(
            id="sc-confirm",
            description="User confirms recipient list before sending",
            metric="Confirmation rate",
            target="100%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-personalize",
            description="Replies are personalized based on email content and tone guidance",
            metric="User satisfaction with reply relevance",
            target="85%",
            weight=0.40,
        ),
    ],
    constraints=[
        Constraint(
            id="c-privacy",
            description="Never send emails without explicit user confirmation; always present recipient list and get approval first",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="c-batch",
            description="Process up to 50 emails per batch",
            constraint_type="hard",
            category="functional",
        ),
    ],
)

# Node list
nodes = [intake_node, search_node, confirm_draft_node]

# Edge definitions
edges = [
    EdgeSpec(
        id="intake-to-search",
        source="intake",
        target="search",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="search-to-confirm",
        source="search",
        target="confirm-draft",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="confirm-to-intake-on-restart",
        source="confirm-draft",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="restart == True",
        priority=2,
    ),
    EdgeSpec(
        id="confirm-to-intake-on-complete",
        source="confirm-draft",
        target="intake",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="batch_complete == True",
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = []

# Module-level vars read by AgentLoader.load()
conversation_mode = "continuous"
identity_prompt = "You are a helpful email reply assistant that filters unreplied emails and sends personalized responses."
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class EmailReplyAgent:
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
            id="email-reply-graph",
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

    def _setup(self):
        self._storage_path = Path.home() / ".hive" / "agents" / "email_reply_agent"
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
            result = await self.trigger_and_wait("default", context, session_state=session_state)
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
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = EmailReplyAgent()
