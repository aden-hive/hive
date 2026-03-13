"""SDR Agent — goal, edges, graph spec, and agent class."""

from pathlib import Path
from typing import Dict, Any

from framework.graph import EdgeCondition, EdgeSpec, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime
from framework.llm.anthropic import AnthropicProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, RuntimeConfig
from .nodes import all_nodes

# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------
goal = Goal(
    id="sdr-outreach",
    name="SDR Lead Processor",
    description=(
        "Research a prospect, qualify them against criteria, and generate "
        "personalized outreach if qualified."
    ),
    success_criteria=[
        SuccessCriterion(
            id="research-completed",
            description="Detailed research on company and prospect is gathered",
            metric="output_contains",
            target="research_summary",
        ),
        SuccessCriterion(
            id="qualification-decision",
            description="Clear qualification decision was made",
            metric="output_contains",
            target="is_qualified",
        ),
        SuccessCriterion(
            id="outreach-generated",
            description="If qualified, a personalized email draft is created",
            metric="custom",
            target="not is_qualified or (email_draft is not None)",
        ),
    ],
    constraints=[
        Constraint(
            id="no-generic-openers",
            description="Do not use 'I hope this email finds you well'",
            constraint_type="soft",
            category="quality",
        ),
        Constraint(
            id="max-length",
            description="Email must be concise (under 200 words)",
            constraint_type="soft",
            category="style",
        ),
    ],
    input_schema={
        "company_name": {"type": "string"},
        "prospect_name": {"type": "string"},
        "prospect_role": {"type": "string"},
        "icp_criteria": {"type": "string"},
        "value_proposition": {"type": "string"},
        "sender_name": {"type": "string"},
    },
    output_schema={
        "research_summary": {"type": "object"},
        "is_qualified": {"type": "boolean"},
        "qualification_reason": {"type": "string"},
        "email_draft": {"type": "string", "optional": True},
        "crm_status": {"type": "string", "optional": True},
    },
)

# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
edges = [
    # Step 1: Research -> Qualify
    EdgeSpec(
        id="research-to-qualify",
        source="research-prospect",
        target="qualify-lead",
        condition=EdgeCondition.ON_SUCCESS,
        description="Pass research data to qualification",
    ),
    # Step 2a: Qualify -> Outreach (If qualified)
    EdgeSpec(
        id="qualify-to-outreach",
        source="qualify-lead",
        target="generate-outreach",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="is_qualified == True",
        description="Generate email only if lead is qualified",
    ),
    # Step 3: Outreach -> Review
    EdgeSpec(
        id="outreach-to-review",
        source="generate-outreach",
        target="review-draft",
        condition=EdgeCondition.ON_SUCCESS,
    ),
    # Step 4a: Review -> Send (Approved)
    EdgeSpec(
        id="review-to-send",
        source="review-draft",
        target="send-email",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved == 'yes' or approved == True",
    ),
    # Step 4b: Review -> Outreach (Rejected)
    EdgeSpec(
        id="review-to-outreach",
        source="review-draft",
        target="generate-outreach",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="approved != 'yes' and approved != True",
    ),
]

# ---------------------------------------------------------------------------
# Graph structure
# ---------------------------------------------------------------------------
entry_node = "research-prospect"
entry_points = {"start": "research-prospect"}
# It can end at qualify-lead (if disqualified) or send-email
terminal_nodes = ["qualify-lead", "send-email"]
pause_nodes = []
nodes = all_nodes


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------
class SDRAgent:
    """Sales Development Representative (SDR) Agent."""

    def __init__(self, config: RuntimeConfig | None = None):
        self.config = config or default_config
        self.goal = goal
        self.nodes = nodes
        self.edges = edges
        self.entry_node = entry_node
        self.terminal_nodes = terminal_nodes
        self.executor = None
        self._tool_registry = None

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="sdr-agent-graph",
            goal_id=self.goal.id,
            entry_node=self.entry_node,
            entry_points=entry_points,
            terminal_nodes=self.terminal_nodes,
            pause_nodes=pause_nodes,
            nodes=self.nodes,
            edges=self.edges,
            default_model=self.config.model,
            max_tokens=self.config.max_tokens,
            description="SDR Research and Outreach Workflow",
        )

    def _setup(self):
        storage_path = Path(self.config.storage_path).expanduser()
        runtime = Runtime(storage_path=storage_path)
        llm = AnthropicProvider(model=self.config.model)

        # Setup tools
        self._tool_registry = ToolRegistry()
        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
        if mcp_config_path.exists():
            self._tool_registry.load_mcp_config(mcp_config_path)

        tool_executor = self._tool_registry.get_executor()
        tools = list(self._tool_registry.get_tools().values())

        self.executor = GraphExecutor(
            runtime=runtime,
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            storage_path=storage_path
        )
        return self.executor

    async def run(self, context: Dict[str, Any], mock_mode: bool = False) -> Dict[str, Any]:
        """Run the agent with the given context."""
        graph = self._build_graph()

        if not self.executor:
            self._setup()

        result = await self.executor.execute(
            graph=graph,
            goal=self.goal,
            input_data=context,
        )

        return {
            "success": result.success,
            "output": result.output,
            "steps": result.steps_executed,
            "path": result.path,
        }


default_agent = SDRAgent()
