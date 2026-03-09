"""Agent graph construction for Sales Call News Researcher."""

from pathlib import Path

from framework.graph import Constraint, EdgeCondition, EdgeSpec, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    calendar_scan_node,
    company_identifier_node,
    email_composer_node,
    email_sender_node,
    news_curator_node,
    news_fetcher_node,
)

goal = Goal(
    id="sales-call-news-researcher-goal",
    name="Sales Call News Researcher",
    description=(
        "Automatically prepares personalized company news briefings before sales calls. "
        "Scans Google Calendar for upcoming meetings, identifies companies, fetches recent "
        "news, curates top articles, composes briefing emails, and sends them to help "
        "sales teams walk into every meeting informed about their prospect's latest developments."
    ),
    success_criteria=[
        SuccessCriterion(
            id="sc-calendar-scan",
            description="Successfully scans calendar and identifies upcoming sales calls",
            metric="calendar_scan_success",
            target="true",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-company-identification",
            description="Correctly identifies and normalizes company names from meetings",
            metric="company_identification_accuracy",
            target=">=80%",
            weight=0.15,
        ),
        SuccessCriterion(
            id="sc-news-coverage",
            description="Fetches relevant recent news for each identified company",
            metric="news_articles_per_company",
            target=">=3",
            weight=0.25,
        ),
        SuccessCriterion(
            id="sc-curation-quality",
            description="Curates news to top 3-5 most relevant articles with summaries",
            metric="curation_relevance",
            target="high",
            weight=0.20,
        ),
        SuccessCriterion(
            id="sc-email-delivery",
            description="Composes and sends personalized briefing emails successfully",
            metric="email_delivery_rate",
            target="100%",
            weight=0.25,
        ),
    ],
    constraints=[
        Constraint(
            id="c-no-fabrication",
            description="Never fabricate news - only report what is found in actual sources",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-relevance",
            description="News must be directly relevant to the company and sales context",
            constraint_type="hard",
            category="quality",
        ),
        Constraint(
            id="c-timeliness",
            description="Prioritize recent news (last 7-30 days) over older articles",
            constraint_type="soft",
            category="quality",
        ),
        Constraint(
            id="c-privacy",
            description="Do not expose sensitive meeting details in email briefings",
            constraint_type="hard",
            category="security",
        ),
    ],
)

nodes = [
    calendar_scan_node,
    company_identifier_node,
    news_fetcher_node,
    news_curator_node,
    email_composer_node,
    email_sender_node,
]

edges = [
    EdgeSpec(
        id="scan-to-identify",
        source="calendar-scan",
        target="company-identifier",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="identify-to-fetch",
        source="company-identifier",
        target="news-fetcher",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="fetch-to-curate",
        source="news-fetcher",
        target="news-curator",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="curate-to-compose",
        source="news-curator",
        target="email-composer",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="compose-to-send",
        source="email-composer",
        target="email-sender",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="send-to-scan",
        source="email-sender",
        target="calendar-scan",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(next_action).lower() == 'scan_again'",
        priority=1,
    ),
]

entry_node = "calendar-scan"
entry_points = {"start": "calendar-scan"}
pause_nodes = []
terminal_nodes = []

conversation_mode = "continuous"
identity_prompt = (
    "You are a Sales Call News Researcher, an intelligent assistant that helps sales "
    "teams prepare for calls by automatically researching companies and delivering "
    "personalized news briefings. You scan calendars, identify companies, fetch relevant "
    "news, curate the most important articles, and compose professional briefing emails. "
    "You are thorough, accurate, and focused on providing actionable insights that help "
    "salespeople have more informed conversations. You never fabricate information and "
    "always cite your sources."
)
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 25,
    "max_history_tokens": 32000,
}


class SalesCallNewsResearcher:
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
            id="sales-call-news-researcher-graph",
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
        self._storage_path = (
            Path.home() / ".hive" / "agents" / "sales_call_news_researcher"
        )
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
        self, entry_point="default", input_data=None, timeout=None, session_state=None
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
            "goal": {"name": self.goal.name, "description": self.goal.description},
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


default_agent = SalesCallNewsResearcher()
