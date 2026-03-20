"""Agent graph construction for BizFlow AI."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    parse_node,
    cv_pipeline_node,
    signal_pipeline_node,
    revenue_pipeline_node,
    contract_pipeline_node,
    hr_pipeline_node,
    merge_node,
    validate_node,
)

# Goal definition
goal = Goal(
    id="bizflow-goal",
    name="BizFlow AI",
    description="Generate multi-pipeline n8n workflows from natural language requirements.",
    success_criteria=[
        SuccessCriterion(
            id="sc-1",
            description="Parse requirements correctly",
            metric="parsing_success",
            target="true",
            weight=0.2,
        ),
        SuccessCriterion(
            id="sc-2",
            description="Generate all requested pipelines",
            metric="pipeline_count",
            target=">=1",
            weight=0.3,
        ),
        SuccessCriterion(
            id="sc-3",
            description="Produce valid n8n workflow JSON",
            metric="validation_passed",
            target="true",
            weight=0.5,
        ),
    ],
    constraints=[
        Constraint(
            id="c-1",
            description="Must produce valid n8n workflow format",
            constraint_type="hard",
            category="functional",
        ),
    ],
)

# Node list
nodes = [
    parse_node,
    cv_pipeline_node,
    signal_pipeline_node,
    revenue_pipeline_node,
    contract_pipeline_node,
    hr_pipeline_node,
    merge_node,
    validate_node,
]

# Edge definitions
edges = [
    # Parse -> all pipeline generators
    EdgeSpec(
        id="parse-to-cv",
        source="parse-requirements",
        target="generate-cv-pipeline",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="parse-to-signal",
        source="parse-requirements",
        target="generate-signal-pipeline",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="parse-to-revenue",
        source="parse-requirements",
        target="generate-revenue-pipeline",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="parse-to-contract",
        source="parse-requirements",
        target="generate-contract-pipeline",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="parse-to-hr",
        source="parse-requirements",
        target="generate-hr-pipeline",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    
    # All pipelines -> merge
    EdgeSpec(
        id="cv-to-merge",
        source="generate-cv-pipeline",
        target="merge-workflows",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="signal-to-merge",
        source="generate-signal-pipeline",
        target="merge-workflows",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="revenue-to-merge",
        source="generate-revenue-pipeline",
        target="merge-workflows",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="contract-to-merge",
        source="generate-contract-pipeline",
        target="merge-workflows",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="hr-to-merge",
        source="generate-hr-pipeline",
        target="merge-workflows",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    
    # Merge -> validate
    EdgeSpec(
        id="merge-to-validate",
        source="merge-workflows",
        target="validate-workflow",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    
    # Feedback loop for revisions
    EdgeSpec(
        id="validate-revise",
        source="validate-workflow",
        target="parse-requirements",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="'revise' in str(output).lower()",
        priority=2,
    ),
]

# Entry point
entry_node = "parse-requirements"
entry_points = {"start": "parse-requirements"}
pause_nodes = []
terminal_nodes = ["validate-workflow"]  # End at validation

# Module-level vars read by AgentRunner.load()
conversation_mode = "continuous"
identity_prompt = "You are an expert n8n workflow automation architect."
loop_config = {
    "max_iterations": 50,
    "max_tool_calls_per_turn": 20,
    "max_history_tokens": 32000,
}


class BizFlowAgent:
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
        from framework.graph import GraphSpec
        
        return GraphSpec(
            id="bizflow-graph",
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
        self._storage_path = Path.home() / ".hive" / "agents" / "bizflow_ai"
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        self._tool_registry = ToolRegistry()
        
        # Load MCP servers if they exist
        mcp_config = Path(__file__).parent / "mcp_servers.json"
        if mcp_config.exists():
            self._tool_registry.load_mcp_config(mcp_config)
        
        llm = LiteLLMProvider(
            model=self.config.model or "gpt-4o-mini",
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
                "default", {"requirements": context.get("requirements", "")}, 
                session_state=session_state
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


default_agent = BizFlowAgent()