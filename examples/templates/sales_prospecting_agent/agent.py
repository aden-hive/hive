"""Agent graph construction for B2B Sales Prospecting & Outreach Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    intake_node,
    lead_search_node,
    company_research_node,
    draft_email_node,
    human_approval_node,
    send_email_node,
)

# Goal definition
goal = Goal(
    id="sales-prospecting",
    name="B2B Sales Prospecting & Outreach",
    description=(
        "Automate the B2B sales workflow: intake target audience, find leads via Apollo, "
        "research companies, draft personalized emails, and send after human approval."
    ),
    success_criteria=[
        SuccessCriterion(
            id="lead-generation",
            description="Agent finds relevant leads matching the target audience using Apollo",
            metric="lead_relevance",
            target="Finds at least 3 relevant leads",
            weight=0.2,
        ),
        SuccessCriterion(
            id="company-research",
            description="Agent gathers firmographic and business context for each lead",
            metric="research_depth",
            target="Identifies key business 'hooks' for personalization",
            weight=0.2,
        ),
        SuccessCriterion(
            id="email-personalization",
            description="Drafts reflect company research and specific value proposition",
            metric="personalization_quality",
            target="Unique opening and context-aware messaging",
            weight=0.2,
        ),
        SuccessCriterion(
            id="human-oversight",
            description="All emails are reviewed and approved by a human before sending",
            metric="approval_rate",
            target="100% human approval for sent emails",
            weight=0.2,
        ),
        SuccessCriterion(
            id="delivery",
            description="Emails are successfully handed off to the email delivery tool",
            metric="send_success",
            target="Successful send status for all approved emails",
            weight=0.2,
        ),
    ],
    constraints=[
        Constraint(
            id="privacy",
            description="Do not use non-public personal information",
            constraint_type="safety",
            category="ethics",
        ),
        Constraint(
            id="anti-spam",
            description="Avoid generic, mass-blast templates; prioritize personalization",
            constraint_type="quality",
            category="content",
        ),
        Constraint(
            id="approval-gate",
            description="Strictly require human approval for email sending",
            constraint_type="safety",
            category="process",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    lead_search_node,
    company_research_node,
    draft_email_node,
    human_approval_node,
    send_email_node,
]

# Edge definitions (linear flow)
edges = [
    EdgeSpec(
        id="intake-to-search",
        source="intake",
        target="lead_search",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    EdgeSpec(
        id="search-to-research",
        source="lead_search",
        target="company_research",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    EdgeSpec(
        id="research-to-draft",
        source="company_research",
        target="draft_email",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    EdgeSpec(
        id="draft-to-approval",
        source="draft_email",
        target="human_approval",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    EdgeSpec(
        id="approval-to-send",
        source="human_approval",
        target="send_email",
        condition=EdgeCondition.ON_SUCCESS,
    ),
]

# Graph configuration for AgentRunner
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["send_email"]


class SalesProspectingAgent:
    """
    B2B Sales Prospecting Agent — 6-node pipeline with human approval.
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
        self._executor: GraphExecutor | None = None
        self._graph: GraphSpec | None = None
        self._event_bus: EventBus | None = None
        self._tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="sales-prospecting-graph",
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
                "max_iterations": 50,
                "max_tool_calls_per_turn": 10,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Set up the executor with all components."""
        from pathlib import Path

        storage_path = Path.home() / ".hive" / "sales_prospecting"
        storage_path.mkdir(parents=True, exist_ok=True)

        self._event_bus = EventBus()
        self._tool_registry = ToolRegistry()

        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        llm = LiteLLMProvider(
            model=self.config.model,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self._graph = self._build_graph()
        runtime = Runtime(storage_path)

        self._executor = GraphExecutor(
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
        """Set up the agent (initialize executor and tools)."""
        if self._executor is None:
            self._setup()

    async def stop(self) -> None:
        """Clean up resources."""
        self._executor = None
        self._event_bus = None

    async def run(
        self, context: dict | None = None, session_state=None
    ) -> ExecutionResult:
        """Run the agent."""
        await self.start()
        try:
            return await self._executor.execute(
                graph=self._graph,
                goal=self.goal,
                input_data=context,
                session_state=session_state,
            )
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

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }


default_agent = SalesProspectingAgent()
