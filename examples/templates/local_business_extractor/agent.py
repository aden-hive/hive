"""Agent graph construction for Local Business Extractor."""

from pathlib import Path
from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

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
import os
import json
import copy
import httpx
from typing import List, Dict, Any
from datetime import datetime

# --- CORE: Bug #804 Fix - Deep Isolation Layer ---
class DeepIsolatedMemory:
    """Ensures read-only nodes cannot mutate shared state via reference leakage."""
    def __init__(self):
        self._storage = {}

    def write(self, key: str, value: Any):
        self._storage[key] = copy.deepcopy(value)

    def read(self, key: str) -> Any:
        return copy.deepcopy(self._storage.get(key))

# --- AGENT: SAP Ariba Procurement Scout ---
class SAPAribaScout:
    def __init__(self, api_key: str, realm: str):
        self.api_key = api_key
        self.realm = realm
        self.base_url = f"https://openapi.ariba.com/api/discovery/v1/{realm}"
        self.keywords = [
            "ai", "artificial intelligence", "software as a service", 
            "plateforme as a service", "cloud", "api", "web3", "robotics", 
            "computer vision", "radar & geographic imaging", 
            "natural language and voice analysis", "video and social media management"
        ]

    async def fetch_opportunities(self) -> List[Dict]:
        """Scans the B2B network for active RFI/RFP postings."""
        all_matches = []
        async with httpx.AsyncClient() as client:
            for query in self.keywords:
                # Note: In production, use OAuth2 headers
                params = {"keywords": query, "status": "PUBLISHED"}
                headers = {"apiKey": self.api_key}
                
                try:
                    response = await client.get(f"{self.base_url}/opportunities", params=params, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        all_matches.extend(data.get("opportunities", []))
                except Exception as e:
                    print(f"Error fetching keyword '{query}': {e}")
        
        # Deduplicate results by ID
        return list({op['id']: op for op in all_matches}.values())

# --- HIVE: Outcome-Driven Orchestrator ---
class HiveProcurementCluster:
    def __init__(self, memory: DeepIsolatedMemory, scout: SAPAribaScout):
        self.memory = memory
        self.scout = scout

    async def run_scout_mission(self):
        print(f"[{datetime.now().isoformat()}] Mission Started: B2B Opportunity Discovery")
        
        # 1. Discovery Phase
        raw_leads = await self.scout.fetch_opportunities()
        self.memory.write("raw_leads", raw_leads)
        
        # 2. Analysis Phase (Logic Node)
        # Here, the 'Queen' would typically generate a response drafter
        leads = self.memory.read("raw_leads")
        print(f"Found {len(leads)} opportunities matching tech-moat keywords.")
        
        for lead in leads:
            print(f" - [MATCH]: {lead.get('title')} | Type: {lead.get('type')} | ID: {lead.get('id')}")
            
        # 3. Draft RFI/RFP (Placeholder for LLM Integration)
        if leads:
            self.memory.write("selected_lead", leads[0])
            print(f"Targeting Lead: {leads[0].get('title')}. Ready for RFI drafting.")

# --- EXECUTION ---
if __name__ == "__main__":
    import asyncio

    # Setup environment
    # In a real Aden Hive setup, these are pulled from a secure vault
    ARIBA_KEY = os.getenv("SAP_ARIBA_API_KEY", "your_api_key_here")
    ARIBA_REALM = os.getenv("SAP_ARIBA_REALM", "your_realm")

    # Initialize Cluster
    shared_mem = DeepIsolatedMemory()
    ariba_scout = SAPAribaScout(ARIBA_KEY, ARIBA_REALM)
    hive = HiveProcurementCluster(shared_mem, ariba_scout)

    # Execute
    asyncio.run(hive.run_scout_mission())
