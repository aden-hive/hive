"""Tests for the AgentBuilder — automatic graph improvement engine."""

from dataclasses import dataclass, field

import pytest

from framework.runtime.builder import AgentBuilder, BuildResult, Modification
from framework.runtime.evaluation import ImprovementPlan


@dataclass
class FakeNodeSpec:
    """Minimal node spec for testing."""

    id: str
    name: str = ""
    system_prompt: str | None = ""
    success_criteria: str | None = ""
    max_retries: int = 3


@dataclass
class FakeGraphSpec:
    """Minimal graph spec for testing."""

    nodes: list = field(default_factory=list)
    version: str = "1.0.0"


@pytest.fixture
def builder() -> AgentBuilder:
    return AgentBuilder()


@pytest.fixture
def simple_graph() -> FakeGraphSpec:
    return FakeGraphSpec(
        nodes=[
            FakeNodeSpec(id="fetch", name="Fetch Data", system_prompt="Fetch data from API."),
            FakeNodeSpec(
                id="process",
                name="Process Data",
                system_prompt="Process the fetched data.",
                success_criteria="accuracy",
            ),
            FakeNodeSpec(id="output", name="Output Results", system_prompt="Format results."),
        ],
        version="1.0.0",
    )


class TestAgentBuilder:
    def test_build_with_empty_plan(self, builder: AgentBuilder, simple_graph: FakeGraphSpec):
        """No modifications when improvement plan has no recommendations."""
        plan = ImprovementPlan()
        result = builder.build(simple_graph, plan)
        # Only improvement context injections (applied to all nodes)
        assert result.improvement_plan_used is True

    def test_build_with_failing_criteria(self, builder: AgentBuilder, simple_graph: FakeGraphSpec):
        """Nodes with matching success_criteria get prompt augmentation."""
        plan = ImprovementPlan(
            recent_success_rate=0.3,
            failing_criteria=["accuracy"],
            recommendations=["Improve accuracy of data processing."],
        )
        result = builder.build(simple_graph, plan)

        # "process" node has success_criteria="accuracy" — should be augmented
        process_node = simple_graph.nodes[1]
        assert "accuracy" in process_node.system_prompt
        assert "builder:criterion:accuracy" in process_node.system_prompt

        # Should have modifications
        assert result.modification_count > 0

    def test_build_with_bottleneck_nodes(self, builder: AgentBuilder, simple_graph: FakeGraphSpec):
        """Bottleneck nodes get retry guidance in their prompts."""
        plan = ImprovementPlan(
            recent_success_rate=0.5,
            bottleneck_nodes=["fetch"],
            recommendations=["Node 'fetch' has high retry rate."],
        )
        result = builder.build(simple_graph, plan)

        fetch_node = simple_graph.nodes[0]
        assert "retry" in fetch_node.system_prompt.lower()
        assert "builder:retry_guidance" in fetch_node.system_prompt

    def test_build_with_restructure_adjusts_retries(
        self, builder: AgentBuilder, simple_graph: FakeGraphSpec
    ):
        """With allow_restructure=True, bottleneck nodes get max_retries bumped."""
        plan = ImprovementPlan(
            bottleneck_nodes=["fetch"],
            recommendations=["Check fetch node."],
        )
        result = builder.build(simple_graph, plan, allow_restructure=True)

        fetch_node = simple_graph.nodes[0]
        assert fetch_node.max_retries == 4  # Bumped from 3 to 4

        retry_mods = [m for m in result.modifications if m.modification_type == "retry_adjust"]
        assert len(retry_mods) >= 1

    def test_build_without_restructure_preserves_retries(
        self, builder: AgentBuilder, simple_graph: FakeGraphSpec
    ):
        """Without allow_restructure, max_retries stays unchanged."""
        plan = ImprovementPlan(
            bottleneck_nodes=["fetch"],
            recommendations=["Check fetch node."],
        )
        result = builder.build(simple_graph, plan, allow_restructure=False)

        fetch_node = simple_graph.nodes[0]
        assert fetch_node.max_retries == 3  # Unchanged

    def test_improvement_context_injected_to_all_nodes(
        self, builder: AgentBuilder, simple_graph: FakeGraphSpec
    ):
        """All nodes get improvement recommendations injected."""
        plan = ImprovementPlan(
            recommendations=["Be more careful with output format.", "Validate schemas."],
        )
        result = builder.build(simple_graph, plan)

        for node in simple_graph.nodes:
            assert "builder:improvement" in node.system_prompt
            assert "Be more careful" in node.system_prompt

    def test_no_duplicate_augmentations(self, builder: AgentBuilder, simple_graph: FakeGraphSpec):
        """Running build twice doesn't duplicate markers."""
        plan = ImprovementPlan(
            failing_criteria=["accuracy"],
            bottleneck_nodes=["fetch"],
            recommendations=["Fix accuracy."],
        )

        builder.build(simple_graph, plan)
        first_prompt = simple_graph.nodes[1].system_prompt

        # Run again
        builder.build(simple_graph, plan)
        second_prompt = simple_graph.nodes[1].system_prompt

        # criterion marker should appear only once
        assert second_prompt.count("builder:criterion:accuracy") == 1

    def test_version_bumped(self, builder: AgentBuilder, simple_graph: FakeGraphSpec):
        """Graph version bumped when modifications are applied."""
        plan = ImprovementPlan(recommendations=["Do better."])
        result = builder.build(simple_graph, plan)

        assert result.graph_version_before == "1.0.0"
        assert simple_graph.version == "1.0.1"
        assert result.graph_version_after == "1.0.1"

    def test_version_not_bumped_on_no_changes(self, builder: AgentBuilder):
        """Version unchanged when no modifications apply."""
        graph = FakeGraphSpec(nodes=[], version="2.0.0")
        plan = ImprovementPlan()  # No recommendations, no failing criteria
        result = builder.build(graph, plan)

        assert graph.version == "2.0.0"

    def test_max_retries_capped_at_5(self, builder: AgentBuilder):
        """max_retries adjustment doesn't exceed 5."""
        graph = FakeGraphSpec(
            nodes=[FakeNodeSpec(id="n1", max_retries=5)],
        )
        plan = ImprovementPlan(
            bottleneck_nodes=["n1"],
            recommendations=["Fix n1."],
        )
        result = builder.build(graph, plan, allow_restructure=True)

        assert graph.nodes[0].max_retries == 5  # Already at cap, no change
        retry_mods = [m for m in result.modifications if m.modification_type == "retry_adjust"]
        assert len(retry_mods) == 0


class TestBuildResult:
    def test_summary_no_modifications(self):
        result = BuildResult()
        assert "No modifications" in result.summary()

    def test_summary_with_modifications(self):
        result = BuildResult(
            modifications=[
                Modification(
                    node_id="n1",
                    modification_type="prompt_augment",
                    description="Added guidance",
                    applied=True,
                ),
                Modification(
                    node_id="n2",
                    modification_type="retry_adjust",
                    description="Bumped retries",
                    applied=False,  # Not applied
                ),
            ]
        )
        assert result.modification_count == 1
        assert "1 modification" in result.summary()
        assert "n1" in result.summary()

    def test_improvement_context_replacement(self, builder: AgentBuilder):
        """Improvement block is replaced on subsequent builds, not duplicated."""
        graph = FakeGraphSpec(
            nodes=[FakeNodeSpec(id="n1", system_prompt="Base prompt.")],
        )

        plan1 = ImprovementPlan(recommendations=["First recommendation."])
        builder.build(graph, plan1)
        assert "First recommendation" in graph.nodes[0].system_prompt

        plan2 = ImprovementPlan(recommendations=["Second recommendation."])
        builder.build(graph, plan2)
        assert "Second recommendation" in graph.nodes[0].system_prompt
        # First should be gone (replaced)
        assert "First recommendation" not in graph.nodes[0].system_prompt

    def test_improvement_marker_single_occurrence(self, builder: AgentBuilder):
        """When improvement marker appears only once (corrupted), strip gracefully."""
        marker = "<!-- builder:improvement -->"
        graph = FakeGraphSpec(
            nodes=[FakeNodeSpec(id="n1", system_prompt=f"Base.{marker}trailing")],
        )
        plan = ImprovementPlan(recommendations=["New rec."])
        builder.build(graph, plan)
        # Old trailing text after single marker is stripped; new block appended
        assert "New rec" in graph.nodes[0].system_prompt
        assert "trailing" not in graph.nodes[0].system_prompt

    def test_bump_version_invalid_format(self, builder: AgentBuilder):
        """Invalid version string gets '.1' appended as fallback."""
        graph = FakeGraphSpec(
            nodes=[FakeNodeSpec(id="n1")],
            version="latest",
        )
        plan = ImprovementPlan(recommendations=["Do something."])
        result = builder.build(graph, plan)
        assert graph.version == "latest.1"
        assert result.graph_version_after == "latest.1"
