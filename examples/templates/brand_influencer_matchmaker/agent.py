"""Agent graph construction for Brand-Influencer Matchmaker Agent."""

from pathlib import Path
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
    brand_analyst_node,
    influencer_discovery_node,
    reasoning_node,
    report_node
)

# Goal definition
goal = Goal(
    id="influencer-match-report",
    name="Brand-Influencer Match Success",
    description=(
        "Analyze brand identity and influencer content to calculate a compatibility "
        "score and produce a strategic sales briefing document."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-brand-dna",
            description="Successfully identified Brand DNA and target audience",
            metric="brand_profile_completeness",
            target="100%",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-influencer-sentiment",
            description="Extracted influencer sentiment and content topics",
            metric="influencer_profile_completeness",
            target="100%",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-match-score",
            description="Calculated a logical compatibility score (0-100)",
            metric="score_generated",
            target="true",
            weight=0.3,
        ),
        SuccessCriterion(
            id="sc-final-brief",
            description="Generated and delivered the sales brief",
            metric="file_delivered",
            target="true",
            weight=0.3,
        ),
    ],
    constraints=[
        Constraint(
            id="no-fabricated-flags",
            description="Never invent 'Red Flags' or controversies that do not exist in search results",
            constraint_type="quality",
            category="accuracy",
        ),
        Constraint(
            id="citation-compliance",
            description="Must cite the specific Brand URL and Influencer Handle in the final report",
            constraint_type="functional",
            category="compliance",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    brand_analyst_node,
    influencer_discovery_node,
    reasoning_node,
    report_node
]

# Edge definitions
edges = [
    # Intake -> Brand Analyst
    EdgeSpec(
        id="intake-to-brand",
        source="intake",
        target="brand_analyst",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Brand Analyst -> Influencer Discovery
    EdgeSpec(
        id="brand-to-influencer",
        source="brand_analyst",
        target="influencer_discovery",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Influencer Discovery -> Reasoning
    EdgeSpec(
        id="influencer-to-reasoning",
        source="influencer_discovery",
        target="reasoning",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Reasoning -> Report Generation
    EdgeSpec(
        id="reasoning-to-report",
        source="reasoning",
        target="report",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "intake"
entry_points = {"start": "intake"}
pause_nodes = []
terminal_nodes = ["report"]


class BrandInfluencerMatchmakerAgent:
    """
    Brand-Influencer Matchmaker Agent.

    Flow: Intake -> Brand Analysis -> Influencer Discovery -> Reasoning -> Report
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
        self.w_tool_registry: ToolRegistry | None = None

    def _build_graph(self) -> GraphSpec:
        """Build the GraphSpec."""
        return GraphSpec(
            id="brand-influencer-matchmaker-graph",
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
                "max_history_tokens": 16000,
            },
        )

    def _setup(self) -> GraphExecutor:
        """Set up the executor with all components."""
        storage_path = Path.home() / ".hive" / "agents" / "brand_influencer_matchmaker"
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

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult | None:
        """Execute the graph and wait for completion."""
        if self._executor is None:
            raise RuntimeError("Agent not started. Call start() first.")
        if self._graph is None:
            raise RuntimeError("Graph not built. Call start() first.")

        return await self._executor.execute(
            graph=self._graph,
            goal=self.goal,
            input_data=input_data,
            session_state=session_state,
        )

    async def run(self, context: dict, session_state=None) -> ExecutionResult:
        """Run the agent (convenience method for single execution)."""
        await self.start()
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

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Create default instance
default_agent = BrandInfluencerMatchmakerAgent()
