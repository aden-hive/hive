"""Agent graph construction for OSS Contributor Accelerator."""

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
    issue_scout_node,
    selection_node,
    contribution_pack_node,
)

# Goal definition
goal = Goal(
    id="oss-contributor-accelerator",
    name="OSS Contributor Accelerator",
    description=(
        "Help contributors systematically identify and execute high-impact "
        "open source contributions through a structured 4-phase process."
    ),
    success_criteria=[
        SuccessCriterion(
            id="profile-completeness",
            description="Contributor profile is complete with skills and goals",
            metric="profile_completion",
            target="100%",
            weight=0.2,
        ),
        SuccessCriterion(
            id="issue-relevance",
            description="Identified issues match contributor skills and interests",
            metric="issue_relevance_score",
            target=">=8/10",
            weight=0.25,
        ),
        SuccessCriterion(
            id="strategic-selection",
            description="Selected issues have clear strategic rationale",
            metric="selection_strategic_score",
            target=">=8/10",
            weight=0.25,
        ),
        SuccessCriterion(
            id="execution-readiness",
            description="Contribution brief provides clear implementation path",
            metric="brief_completeness",
            target="100%",
            weight=0.3,
        ),
    ],
    constraints=[
        Constraint(
            id="time-bound",
            description="Process should complete within reasonable timeframe",
            metric="session_duration",
            constraint="<=2 hours",
        ),
        Constraint(
            id="focused-scope",
            description="Limit to 1-3 selected issues for focus",
            metric="selected_issues_count",
            constraint="<=3",
        ),
    ],
)

# Graph specification
graph = GraphSpec(
    nodes=[
        intake_node,
        issue_scout_node,
        selection_node,
        contribution_pack_node,
    ],
    edges=[
        # Intake → Issue Scout
        EdgeSpec(
            from_node="intake",
            to_node="issue-scout",
            condition=EdgeCondition(
                description="Proceed when contributor profile and target repo are collected",
                expression="contributor_profile != null AND target_repo != null AND contribution_goals != null",
            ),
        ),
        # Issue Scout → Selection
        EdgeSpec(
            from_node="issue-scout",
            to_node="selection",
            condition=EdgeCondition(
                description="Proceed when ranked issues are ready for review",
                expression="ranked_issues != null AND issue_analysis != null",
            ),
        ),
        # Selection → Contribution Pack
        EdgeSpec(
            from_node="selection",
            to_node="contribution-pack",
            condition=EdgeCondition(
                description="Proceed when contributor has selected target issues",
                expression="selected_issues != null AND selection_rationale != null",
            ),
        ),
    ],
    entry_point=EntryPointSpec(
        node_id="intake",
        initial_input_key="initial_request",
    ),
)

# Agent class
class OSSContributorAccelerator:
    """OSS Contributor Accelerator agent for systematic open source contributions."""
    
    def __init__(self, config=None):
        self.config = config or default_config
        self.goal = goal
        self.graph = graph
        self.metadata = metadata
        
    def create_runtime(self, tool_registry: ToolRegistry) -> AgentRuntime:
        """Create and configure the agent runtime."""
        return create_agent_runtime(
            goal=self.goal,
            graph=self.graph,
            llm_provider=LiteLLMProvider(
                model=self.config.llm_model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            ),
            tool_registry=tool_registry,
            checkpoint_config=CheckpointConfig(
                enabled=self.config.checkpoints_enabled,
                directory=Path(self.config.checkpoint_dir),
            ),
        )
    
    def execute(self, input_data: dict, tool_registry: ToolRegistry) -> ExecutionResult:
        """Execute the agent with the given input."""
        runtime = self.create_runtime(tool_registry)
        return runtime.execute(input_data)

# Export the agent specification
__all__ = [
    "OSSContributorAccelerator",
    "goal",
    "graph",
    "metadata",
]
