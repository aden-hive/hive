"""Linear Triage & Auto-Labeling Agent — Router Pattern implementation.

This agent demonstrates the Router Pattern with Conditional Edges:
1. EntryPoint (classify): Classifies raw issue descriptions
2. Conditional routing based on issue_type:
   - security -> SecurityNode (high-priority escalation)
   - bug -> BugNode (reproduction steps, root causes)
   - feature -> FeatureNode (roadmap alignment)
3. All branches converge at ActionNode (save Linear API payload)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from framework.graph import Constraint, Goal, SuccessCriterion
from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import ExecutionResult
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

from .config import default_config, metadata
from .nodes import (
    action_node,
    bug_node,
    classify_node,
    feature_node,
    security_node,
)

if TYPE_CHECKING:
    pass

goal = Goal(
    id="linear-triage-goal",
    name="Linear Triage & Auto-Labeling",
    description=(
        "Autonomous triage agent that classifies issues (Bug, Feature, Security), "
        "determines priority, routes to specialized processing nodes, and generates "
        "a simulated Linear API payload."
    ),
    success_criteria=[
        SuccessCriterion(
            id="classification-complete",
            description="Issue is correctly classified with type, severity, and labels",
            metric="classification_accuracy",
            target=">=0.9",
            weight=0.3,
        ),
        SuccessCriterion(
            id="appropriate-routing",
            description="Issue is routed to the correct specialized node based on type",
            metric="routing_accuracy",
            target="1.0",
            weight=0.25,
        ),
        SuccessCriterion(
            id="quality-analysis",
            description="Specialized node produces relevant and actionable analysis",
            metric="analysis_quality",
            target=">=0.8",
            weight=0.25,
        ),
        SuccessCriterion(
            id="payload-saved",
            description="Final Linear API payload is saved to disk",
            metric="payload_persisted",
            target="true",
            weight=0.2,
        ),
    ],
    constraints=[
        Constraint(
            id="no-duplicate-processing",
            description="Each issue should only be processed once by one specialized node",
            constraint_type="hard",
            category="functional",
        ),
        Constraint(
            id="valid-json-output",
            description="All classification outputs must be valid JSON",
            constraint_type="hard",
            category="quality",
        ),
    ],
)

nodes = [classify_node, security_node, bug_node, feature_node, action_node]

edges = [
    EdgeSpec(
        id="classify-to-security",
        source="classify",
        target="security",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(issue_type).lower() == 'security'",
        priority=3,
        description="Route security issues to security node",
    ),
    EdgeSpec(
        id="classify-to-bug",
        source="classify",
        target="bug",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(issue_type).lower() == 'bug'",
        priority=2,
        description="Route bug reports to bug node",
    ),
    EdgeSpec(
        id="classify-to-feature",
        source="classify",
        target="feature",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="str(issue_type).lower() == 'feature'",
        priority=1,
        description="Route feature requests to feature node",
    ),
    EdgeSpec(
        id="security-to-action",
        source="security",
        target="action",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
        description="Security analysis to action node",
    ),
    EdgeSpec(
        id="bug-to-action",
        source="bug",
        target="action",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
        description="Bug analysis to action node",
    ),
    EdgeSpec(
        id="feature-to-action",
        source="feature",
        target="action",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
        description="Feature analysis to action node",
    ),
]

entry_node = "classify"
entry_points = {"start": "classify"}
pause_nodes = []
terminal_nodes = ["action"]

conversation_mode = "continuous"
identity_prompt = (
    "You are a Linear Triage & Auto-Labeling Agent. "
    "Your purpose is to classify issues, route them to specialized processing, "
    "and generate simulated Linear API payloads."
)
loop_config = {
    "max_iterations": 10,
    "max_tool_calls_per_turn": 5,
    "max_history_tokens": 16000,
}


class LinearTriageAgent:
    """Linear Triage & Auto-Labeling Agent with Router Pattern.

    Demonstrates the Router Pattern using Conditional Edges:
    - ClassifyNode routes to Security/Bug/Feature based on issue_type
    - All branches converge at ActionNode

    Usage:
        agent = LinearTriageAgent()
        result = await agent.run({"raw_issue": "Login crashes on Safari"})
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

    def _build_graph(self) -> GraphSpec:
        return GraphSpec(
            id="linear-triage-graph",
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

    def _setup(self) -> None:
        self._storage_path = Path.home() / ".hive" / "agents" / "linear_triage_agent"
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
                    id="start",
                    name="Triage Issue",
                    entry_node=self.entry_node,
                    trigger_type="manual",
                    isolation_level="isolated",
                )
            ],
            llm=llm,
            tools=tools,
            tool_executor=tool_executor,
            checkpoint_config=CheckpointConfig(enabled=False),
            graph_id="linear_triage_agent",
        )

    async def start(self) -> None:
        """Set up and start the agent runtime."""
        if self._agent_runtime is None:
            self._setup()
        if not self._agent_runtime.is_running:
            await self._agent_runtime.start()

    async def stop(self) -> None:
        """Stop the agent runtime."""
        if self._agent_runtime and self._agent_runtime.is_running:
            await self._agent_runtime.stop()
        self._agent_runtime = None

    async def run(self, context: dict, session_state: dict | None = None) -> ExecutionResult:
        """Run the agent with the given context.

        Args:
            context: Must contain 'raw_issue' key with the issue description
            session_state: Optional session state for resuming

        Returns:
            ExecutionResult with success status and output
        """
        await self.start()
        try:
            result = await self._agent_runtime.trigger_and_wait(
                entry_point_id="start",
                input_data=context,
                session_state=session_state,
            )
            return result or ExecutionResult(success=False, error="Execution timeout")
        finally:
            await self.stop()

    def info(self) -> dict:
        """Return agent information."""
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
            "pattern": "Router Pattern with Conditional Edges",
        }

    def validate(self) -> dict:
        """Validate graph wiring and entry-point contract."""
        errors = []
        warnings = []
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

        if not isinstance(self.entry_points, dict):
            errors.append(
                "Invalid entry_points: expected dict[str, str] like "
                "{'start': '<entry-node-id>'}. "
                f"Got {type(self.entry_points).__name__}."
            )
        else:
            if "start" not in self.entry_points:
                errors.append("entry_points must include 'start' mapped to entry_node.")
            else:
                start_node = self.entry_points.get("start")
                if start_node != self.entry_node:
                    errors.append(
                        f"entry_points['start'] points to '{start_node}' "
                        f"but entry_node is '{self.entry_node}'."
                    )

            for ep_id, nid in self.entry_points.items():
                if not isinstance(ep_id, str):
                    errors.append(
                        f"Invalid entry_points key {ep_id!r} "
                        f"({type(ep_id).__name__}). Entry point names must be strings."
                    )
                    continue
                if not isinstance(nid, str):
                    errors.append(
                        f"Invalid entry_points['{ep_id}']={nid!r} "
                        f"({type(nid).__name__}). Node ids must be strings."
                    )
                    continue
                if nid not in node_ids:
                    errors.append(
                        f"Entry point '{ep_id}' references unknown node '{nid}'. "
                        f"Known nodes: {sorted(node_ids)}"
                    )

        for n in self.nodes:
            outgoing = [e for e in self.edges if e.source == n.id]
            if not outgoing and n.id not in self.terminal_nodes:
                warnings.append(f"Node '{n.id}' has no outgoing edges and is not a terminal node.")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


default_agent = LinearTriageAgent()
