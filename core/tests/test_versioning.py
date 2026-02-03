"""Tests for agent versioning and rollback."""

import json
import tempfile
from pathlib import Path

import pytest

from framework.graph import Goal
from framework.graph.edge import GraphSpec
from framework.graph.goal import Constraint, SuccessCriterion
from framework.graph.node import NodeSpec
from framework.runner.ab_testing import ABTestRouter, create_ab_test_session
from framework.runner.versioning import AgentVersionManager
from framework.schemas.version import BumpType, VersionStatus


@pytest.fixture
def temp_versions_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_goal():
    return Goal(
        id="test-goal",
        name="Test Agent",
        description="A test agent for versioning",
        success_criteria=[
            SuccessCriterion(
                id="sc1",
                description="Complete successfully",
                metric="success_rate",
                target="1.0",
                weight=1.0,
            )
        ],
        constraints=[
            Constraint(
                id="c1",
                description="No errors",
                constraint_type="hard",
                category="safety",
                check="error == null",
            )
        ],
    )


@pytest.fixture
def sample_graph():
    return GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        version="1.0.0",
        entry_node="start",
        terminal_nodes=["end"],
        nodes=[
            NodeSpec(
                id="start",
                node_type="input",
                name="Start",
                description="Entry point",
                input_keys=["input"],
                output_keys=["output"],
            ),
            NodeSpec(
                id="end",
                node_type="output",
                name="End",
                description="Exit point",
                input_keys=["result"],
                output_keys=["final"],
            ),
        ],
        edges=[],
    )


class TestAgentVersionManager:

    def test_init_creates_directories(self, temp_versions_dir):
        manager = AgentVersionManager(temp_versions_dir)
        assert temp_versions_dir.exists()

    def test_save_first_version(self, temp_versions_dir, sample_graph, sample_goal):
        manager = AgentVersionManager(temp_versions_dir)

        version = manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Initial version",
            bump=BumpType.PATCH,
        )

        assert version.version == "1.0.0"
        assert version.agent_id == "test-agent"
        assert version.description == "Initial version"
        assert version.status == VersionStatus.ACTIVE

        version_file = temp_versions_dir / "test-agent" / "versions" / "1.0.0.json"
        assert version_file.exists()

        registry_file = temp_versions_dir / "test-agent" / "registry.json"
        assert registry_file.exists()

    def test_save_multiple_versions(self, temp_versions_dir, sample_graph, sample_goal):
        manager = AgentVersionManager(temp_versions_dir)

        v1 = manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Initial version",
            bump=BumpType.PATCH,
        )
        assert v1.version == "1.0.0"

        v2 = manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Bug fix",
            bump=BumpType.PATCH,
        )
        assert v2.version == "1.0.1"

        v3 = manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="New feature",
            bump=BumpType.MINOR,
        )
        assert v3.version == "1.1.0"

        v4 = manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Breaking change",
            bump=BumpType.MAJOR,
        )
        assert v4.version == "2.0.0"

    def test_load_version(self, temp_versions_dir, sample_graph, sample_goal):
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version 1",
            bump=BumpType.PATCH,
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version 2",
            bump=BumpType.PATCH,
        )

        version = manager.load_version("test-agent", "1.0.0")
        assert version.version == "1.0.0"
        assert version.description == "Version 1"

        current = manager.load_version("test-agent")
        assert current.version == "1.0.1"
        assert current.description == "Version 2"

    def test_rollback(self, temp_versions_dir, sample_graph, sample_goal):
        """Test rolling back to a previous version."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version 1.0.0",
            bump=BumpType.PATCH,
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version 1.0.1",
            bump=BumpType.PATCH,
        )

        # Current should be 1.0.1
        registry = manager._load_registry("test-agent")
        assert registry.current_version == "1.0.1"

        # Rollback to 1.0.0
        graph, goal = manager.rollback("test-agent", "1.0.0")
        assert graph.id == "test-graph"
        assert goal.id == "test-goal"

        # Check current version updated
        registry = manager._load_registry("test-agent")
        assert registry.current_version == "1.0.0"

    def test_list_versions(self, temp_versions_dir, sample_graph, sample_goal):
        """Test listing all versions"""
        manager = AgentVersionManager(temp_versions_dir)

        for i in range(3):
            manager.save_version(
                agent_id="test-agent",
                graph=sample_graph,
                goal=sample_goal,
                description=f"Version {i}",
                bump=BumpType.PATCH,
            )

        versions = manager.list_versions("test-agent")
        assert len(versions) == 3
        assert versions[0].version == "1.0.0"
        assert versions[1].version == "1.0.1"
        assert versions[2].version == "1.0.2"

    def test_compare_versions(self, temp_versions_dir, sample_goal):
        """Test comparing two versions."""
        manager = AgentVersionManager(temp_versions_dir)

        # Create graph v1
        graph_v1 = GraphSpec(
            id="test-graph",
            goal_id="test-goal",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[
                NodeSpec(
                    id="start",
                    node_type="input",
                    name="Start",
                    description="Entry",
                    input_keys=[],
                    output_keys=[],
                )
            ],
            edges=[],
        )

        manager.save_version(
            agent_id="test-agent",
            graph=graph_v1,
            goal=sample_goal,
            description="Version 1",
        )

        # Create graph v2 with additional node
        graph_v2 = GraphSpec(
            id="test-graph",
            goal_id="test-goal",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[
                NodeSpec(
                    id="start",
                    node_type="input",
                    name="Start",
                    description="Entry",
                    input_keys=[],
                    output_keys=[],
                ),
                NodeSpec(
                    id="middle",
                    node_type="process",
                    name="Middle",
                    description="Processing",
                    input_keys=[],
                    output_keys=[],
                ),
            ],
            edges=[],
        )

        manager.save_version(
            agent_id="test-agent",
            graph=graph_v2,
            goal=sample_goal,
            description="Version 2",
            bump=BumpType.MINOR,
        )

        diff = manager.compare_versions("test-agent", "1.0.0", "1.1.0")

        assert diff.from_version == "1.0.0"
        assert diff.to_version == "1.1.0"
        assert len(diff.nodes_added) == 1
        assert "middle" in diff.nodes_added
        assert len(diff.nodes_removed) == 0
        assert "1 nodes added" in diff.summary

    def test_tag_version(self, temp_versions_dir, sample_graph, sample_goal):
        """Test tagging versions."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Release version",
        )

        manager.tag_version("test-agent", "1.0.0", "production")

        # Retrieve by tag
        version = manager.get_version_by_tag("test-agent", "production")
        assert version == "1.0.0"

    def test_delete_version(self, temp_versions_dir, sample_graph, sample_goal):
        """Test deleting (archiving) a version."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version 1",
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version 2",
            bump=BumpType.PATCH,
        )

        # Delete old version
        manager.delete_version("test-agent", "1.0.0")

        # Load and check status
        version = manager.load_version("test-agent", "1.0.0")
        assert version.status == VersionStatus.ARCHIVED

        # Cannot delete current version
        with pytest.raises(ValueError, match="Cannot delete current version"):
            manager.delete_version("test-agent", "1.0.1")


class TestABTesting:
    """Test A/B testing functionality."""

    def test_create_ab_test(self, temp_versions_dir, sample_graph, sample_goal):
        """Test creating an A/B test configuration."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version A",
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version B",
            bump=BumpType.MINOR,
        )

        config = manager.create_ab_test(
            agent_id="test-agent",
            version_a="1.0.0",
            version_b="1.1.0",
            traffic_split=0.6,
            metrics=["response_time", "success_rate"],
        )

        assert config.agent_id == "test-agent"
        assert config.version_a == "1.0.0"
        assert config.version_b == "1.1.0"
        assert config.traffic_split == 0.6
        assert "response_time" in config.metrics

    def test_ab_test_routing(self, temp_versions_dir, sample_graph, sample_goal):
        """Test consistent routing in A/B tests."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version A",
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version B",
            bump=BumpType.MINOR,
        )

        config = manager.create_ab_test(
            agent_id="test-agent",
            version_a="1.0.0",
            version_b="1.1.0",
            traffic_split=0.5,
        )

        router = ABTestRouter(manager, config)

        # Same request ID should always route to same version
        v1 = router.route("request-123")
        v2 = router.route("request-123")
        assert v1 == v2

        # Different requests might go to different versions
        v3 = router.route("request-456")
        assert v3 in ["1.0.0", "1.1.0"]

    def test_ab_test_record_execution(self, temp_versions_dir, sample_graph, sample_goal):
        """Test recording execution metrics."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version A",
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version B",
            bump=BumpType.MINOR,
        )

        config = manager.create_ab_test(
            agent_id="test-agent",
            version_a="1.0.0",
            version_b="1.1.0",
            traffic_split=0.5,
            metrics=["response_time"],
        )

        router = ABTestRouter(manager, config)

        router.record_execution(
            request_id="req1",
            version="1.0.0",
            metrics={"response_time": 0.5},
        )
        router.record_execution(
            request_id="req2",
            version="1.0.0",
            metrics={"response_time": 0.7},
        )
        router.record_execution(
            request_id="req3",
            version="1.1.0",
            metrics={"response_time": 0.3},
        )

        results = router.get_results()
        assert results.executions_a == 2
        assert results.executions_b == 1
        assert results.metrics_a["response_time"] == 0.6
        assert results.metrics_b["response_time"] == 0.3

    def test_ab_test_analyze_results(self, temp_versions_dir, sample_graph, sample_goal):
        """Test analyzing A/B test results."""
        manager = AgentVersionManager(temp_versions_dir)

        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version A",
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version B",
            bump=BumpType.MINOR,
        )

        config = manager.create_ab_test(
            agent_id="test-agent",
            version_a="1.0.0",
            version_b="1.1.0",
            metrics=["success_rate"],
        )

        router = ABTestRouter(manager, config)

        # Record results
        for i in range(30):
            router.record_execution(
                request_id=f"req_a_{i}",
                version="1.0.0",
                metrics={"success_rate": 0.8},
            )

        for i in range(30):
            router.record_execution(
                request_id=f"req_b_{i}",
                version="1.1.0",
                metrics={"success_rate": 0.9},
            )

        analysis = router.analyze_results(primary_metric="success_rate")

        assert analysis["executions"]["version_a"] == 30
        assert analysis["executions"]["version_b"] == 30
        assert analysis["metrics_comparison"]["success_rate"]["better"] == "version_b"
        assert analysis["winner"] == "version_b"
        assert analysis["confidence"] is not None

    def test_create_ab_test_session(self, temp_versions_dir, sample_graph, sample_goal):
        """Test convenience function for creating A/B test session."""
        manager = AgentVersionManager(temp_versions_dir)

        # Setup versions
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version A",
        )
        manager.save_version(
            agent_id="test-agent",
            graph=sample_graph,
            goal=sample_goal,
            description="Version B",
            bump=BumpType.MINOR,
        )

        router = create_ab_test_session(
            agent_id="test-agent",
            version_a="1.0.0",
            version_b="1.1.0",
            traffic_split=0.5,
            metrics=["response_time"],
            versions_dir=temp_versions_dir,
        )

        assert isinstance(router, ABTestRouter)
        assert router.config.agent_id == "test-agent"


class TestVersionParsing:
    """Test version parsing and bumping"""

    def test_parse_version(self, temp_versions_dir):
        """Test parsing semantic version strings"""
        manager = AgentVersionManager(temp_versions_dir)

        assert manager._parse_version("1.2.3") == (1, 2, 3)
        assert manager._parse_version("0.0.1") == (0, 0, 1)
        assert manager._parse_version("10.20.30") == (10, 20, 30)

    def test_parse_invalid_version(self, temp_versions_dir):
        """Test parsing invalid version strings"""
        manager = AgentVersionManager(temp_versions_dir)

        with pytest.raises(ValueError, match="Invalid version format"):
            manager._parse_version("1.2")

        with pytest.raises(ValueError, match="Invalid version format"):
            manager._parse_version("1.2.3.4")

        with pytest.raises(ValueError, match="Parts must be integers"):
            manager._parse_version("1.2.x")

    def test_bump_version(self, temp_versions_dir):
        """Test version bumping"""
        manager = AgentVersionManager(temp_versions_dir)

        assert manager._bump_version("1.2.3", BumpType.PATCH) == "1.2.4"
        assert manager._bump_version("1.2.3", BumpType.MINOR) == "1.3.0"
        assert manager._bump_version("1.2.3", BumpType.MAJOR) == "2.0.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
