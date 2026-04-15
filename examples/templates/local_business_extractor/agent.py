"""Agent graph construction for Local Business Extractor."""

from pathlib import Path
from framework.orchestrator import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.orchestrator import ExecutionResult
from framework.orchestrator.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.loader.tool_registry import ToolRegistry
from framework.host.agent_host import AgentHost
from framework.host.execution_manager import EntryPointSpec

from .config import default_config, metadata
from .nodes import map_search_gcu, extract_contacts_node, sheets_sync_node

goal = Goal(
    id="local-business-extraction",
    name="Local Business Extraction",
    description="Find local businesses on Maps, extract contacts, and sync to Google Sheets.",
    success_criteria=[
        SuccessCriterion(
            id="sc-1",
            description="Extract business details from Maps",
            metric="count",
            target="5",
            weight=0.5,
        ),
        SuccessCriterion(
            id="sc-2",
            description="Sync data to Google Sheets",
            metric="success_rate",
            target="1.0",
            weight=0.5,
        ),
    ],
    constraints=[
        Constraint(
            id="c-1",
            description="Must verify website presence before scraping",
            constraint_type="hard",
            category="quality",
        ),
    ],
)

nodes = [map_search_gcu, extract_contacts_node, sheets_sync_node]

edges = [
    EdgeSpec(
        id="extract-to-sheets",
        source="extract-contacts",
        target="sheets-sync",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # Loop back for new tasks
    EdgeSpec(
        id="sheets-to-extract",
        source="sheets-sync",
        target="extract-contacts",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
]

entry_node = "extract-contacts"
entry_points = {"start": "extract-contacts"}
pause_nodes = []
terminal_nodes = []

conversation_mode = "continuous"
identity_prompt = "You are a lead generation specialist focused on local businesses."
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}


class LocalBusinessExtractor:
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
            id="local-business-extractor-graph",
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
        self._storage_path = Path.home() / ".hive" / "agents" / "local_business_extractor"
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
        self._agent_runtime = AgentHost(
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
                )
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(enabled=True, checkpoint_on_node_complete=True),
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

    async def run(self, context, session_state=None):
        await self.start()
        try:
            result = await self._agent_runtime.trigger_and_wait(
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
        }

    def validate(self):
        """Validate agent structure."""
        errors = []
        warnings = []
        node_ids = {n.id for n in self.nodes}
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge {edge.id}: source '{edge.source}' not found")
            if edge.target not in node_ids:
                errors.append(f"Edge {edge.id}: target '{edge.target}' not found")
        if self.entry_node not in node_ids:
            errors.append(f"Entry node '{self.entry_node}' not found")
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = LocalBusinessExtractor()
