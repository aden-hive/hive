"""Tests for Agent QA Pipeline agent structure."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def agent_json_path():
    return Path(__file__).parent.parent / "agent.json"


@pytest.fixture
def agent_spec(agent_json_path):
    with open(agent_json_path) as f:
        return json.load(f)


class TestAgentQAPipelineStructure:
    """Test the structural integrity of the Agent QA Pipeline agent."""

    def test_agent_json_exists(self, agent_json_path):
        """agent.json file exists."""
        assert agent_json_path.exists(), "agent.json file not found"

    def test_agent_has_required_fields(self, agent_spec):
        """Agent spec has all required top-level fields."""
        assert "agent" in agent_spec
        assert "graph" in agent_spec
        assert "goal" in agent_spec
        assert "required_tools" in agent_spec
        assert "metadata" in agent_spec

    def test_agent_metadata(self, agent_spec):
        """Agent metadata is correct."""
        assert agent_spec["agent"]["id"] == "agent_qa_pipeline"
        assert agent_spec["agent"]["name"] == "Agent QA Pipeline"
        assert agent_spec["metadata"]["node_count"] == 13
        assert agent_spec["metadata"]["edge_count"] == 17

    def test_graph_has_entry_node(self, agent_spec):
        """Graph has entry node defined."""
        graph = agent_spec["graph"]
        assert "entry_node" in graph
        assert graph["entry_node"] == "intake"

    def test_graph_has_terminal_nodes(self, agent_spec):
        """Graph has terminal nodes defined."""
        graph = agent_spec["graph"]
        assert "terminal_nodes" in graph
        assert len(graph["terminal_nodes"]) > 0
        assert "deliver-report" in graph["terminal_nodes"]

    def test_graph_has_pause_nodes(self, agent_spec):
        """Graph has pause nodes for HITL."""
        graph = agent_spec["graph"]
        assert "pause_nodes" in graph
        assert "review-test-plan" in graph["pause_nodes"]

    def test_all_nodes_have_required_fields(self, agent_spec):
        """All nodes have required fields."""
        required_fields = [
            "id",
            "name",
            "description",
            "node_type",
            "input_keys",
            "output_keys",
        ]
        for node in agent_spec["graph"]["nodes"]:
            for field in required_fields:
                assert field in node, (
                    f"Node {node.get('id', 'unknown')} missing field {field}"
                )

    def test_all_edges_have_required_fields(self, agent_spec):
        """All edges have required fields."""
        required_fields = ["id", "source", "target", "condition"]
        for edge in agent_spec["graph"]["edges"]:
            for field in required_fields:
                assert field in edge, (
                    f"Edge {edge.get('id', 'unknown')} missing field {field}"
                )

    def test_node_ids_are_unique(self, agent_spec):
        """All node IDs are unique."""
        node_ids = [node["id"] for node in agent_spec["graph"]["nodes"]]
        assert len(node_ids) == len(set(node_ids)), "Duplicate node IDs found"

    def test_edge_ids_are_unique(self, agent_spec):
        """All edge IDs are unique."""
        edge_ids = [edge["id"] for edge in agent_spec["graph"]["edges"]]
        assert len(edge_ids) == len(set(edge_ids)), "Duplicate edge IDs found"

    def test_all_edge_sources_exist(self, agent_spec):
        """All edge sources reference existing nodes."""
        node_ids = {node["id"] for node in agent_spec["graph"]["nodes"]}
        for edge in agent_spec["graph"]["edges"]:
            assert edge["source"] in node_ids, (
                f"Edge {edge['id']} has invalid source {edge['source']}"
            )

    def test_all_edge_targets_exist(self, agent_spec):
        """All edge targets reference existing nodes."""
        node_ids = {node["id"] for node in agent_spec["graph"]["nodes"]}
        for edge in agent_spec["graph"]["edges"]:
            assert edge["target"] in node_ids, (
                f"Edge {edge['id']} has invalid target {edge['target']}"
            )

    def test_entry_node_exists(self, agent_spec):
        """Entry node exists in nodes list."""
        node_ids = {node["id"] for node in agent_spec["graph"]["nodes"]}
        assert agent_spec["graph"]["entry_node"] in node_ids, (
            "Entry node not found in nodes list"
        )

    def test_terminal_nodes_exist(self, agent_spec):
        """All terminal nodes exist in nodes list."""
        node_ids = {node["id"] for node in agent_spec["graph"]["nodes"]}
        for term in agent_spec["graph"]["terminal_nodes"]:
            assert term in node_ids, f"Terminal node {term} not found in nodes list"

    def test_pause_nodes_exist(self, agent_spec):
        """All pause nodes exist in nodes list."""
        node_ids = {node["id"] for node in agent_spec["graph"]["nodes"]}
        for pause in agent_spec["graph"]["pause_nodes"]:
            assert pause in node_ids, f"Pause node {pause} not found in nodes list"


class TestAgentQAPipelineFeatures:
    """Test that the Agent QA Pipeline demonstrates required framework features."""

    def test_has_fan_out_pattern(self, agent_spec):
        """Graph has fan-out pattern (review-test-plan -> 3 test runners)."""
        edges = agent_spec["graph"]["edges"]
        fan_out_sources = {}
        for edge in edges:
            if edge["condition"] == "on_success":
                source = edge["source"]
                if source not in fan_out_sources:
                    fan_out_sources[source] = []
                fan_out_sources[source].append(edge["target"])

        fan_outs = {k: v for k, v in fan_out_sources.items() if len(v) > 1}
        assert len(fan_outs) > 0, "No fan-out patterns found"

        assert "review-test-plan" in fan_outs, (
            "review-test-plan should fan-out to test runners"
        )
        assert len(fan_outs["review-test-plan"]) == 3, (
            "review-test-plan should fan-out to 3 test runners"
        )

    def test_has_fan_in_pattern(self, agent_spec):
        """Graph has fan-in pattern (3 test runners -> aggregate-results)."""
        edges = agent_spec["graph"]["edges"]
        fan_in_targets = {}
        for edge in edges:
            target = edge["target"]
            if target not in fan_in_targets:
                fan_in_targets[target] = []
            fan_in_targets[target].append(edge["source"])

        fan_ins = {k: v for k, v in fan_in_targets.items() if len(v) > 1}
        assert len(fan_ins) > 0, "No fan-in patterns found"

        assert "aggregate-results" in fan_ins, (
            "aggregate-results should be a fan-in point"
        )
        assert len(fan_ins["aggregate-results"]) == 3, (
            "aggregate-results should receive from 3 test runners"
        )

    def test_has_on_failure_edge(self, agent_spec):
        """Graph has on_failure edge for graceful error handling."""
        edges = agent_spec["graph"]["edges"]
        on_failure_edges = [e for e in edges if e["condition"] == "on_failure"]
        assert len(on_failure_edges) > 0, "No on_failure edges found"

        load_agent_fail = [e for e in on_failure_edges if e["source"] == "load-agent"]
        assert len(load_agent_fail) > 0, "load-agent should have on_failure edge"

    def test_has_conditional_routing(self, agent_spec):
        """Graph has conditional routing for verdict-based paths."""
        edges = agent_spec["graph"]["edges"]
        conditional_edges = [e for e in edges if e["condition"] == "conditional"]
        assert len(conditional_edges) >= 2, (
            "Should have at least 2 conditional edges for verdict routing"
        )

        judge_edges = [e for e in conditional_edges if e["source"] == "judge-quality"]
        assert len(judge_edges) >= 2, "judge-quality should have conditional routing"

    def test_has_feedback_loop(self, agent_spec):
        """Graph has feedback loop for fix/re-test cycle."""
        edges = agent_spec["graph"]["edges"]
        feedback_edges = [
            e for e in edges if "load-agent" in e["target"] and e["source"] != "intake"
        ]
        assert len(feedback_edges) > 0, "No feedback loop found"

        fix_feedback = [e for e in feedback_edges if e["source"] == "request-fixes"]
        assert len(fix_feedback) > 0, "request-fixes should have feedback to load-agent"

    def test_feedback_loop_has_max_visits(self, agent_spec):
        """Feedback loop node has max_node_visits set."""
        request_fixes = None
        for node in agent_spec["graph"]["nodes"]:
            if node["id"] == "request-fixes":
                request_fixes = node
                break

        assert request_fixes is not None, "request-fixes node not found"
        assert request_fixes.get("max_node_visits", 0) > 0, (
            "request-fixes should have max_node_visits > 0"
        )

    def test_hitl_pause_node_is_client_facing(self, agent_spec):
        """HITL pause node is client_facing."""
        review_node = None
        for node in agent_spec["graph"]["nodes"]:
            if node["id"] == "review-test-plan":
                review_node = node
                break

        assert review_node is not None, "review-test-plan node not found"
        assert review_node.get("client_facing", False), (
            "review-test-plan should be client_facing"
        )

    def test_all_13_nodes_present(self, agent_spec):
        """All 13 expected nodes are present."""
        expected_nodes = [
            "intake",
            "load-agent",
            "static-analysis",
            "generate-test-plan",
            "review-test-plan",
            "run-functional",
            "run-resilience",
            "run-security",
            "aggregate-results",
            "judge-quality",
            "generate-report",
            "deliver-report",
            "request-fixes",
        ]
        node_ids = {node["id"] for node in agent_spec["graph"]["nodes"]}
        for expected in expected_nodes:
            assert expected in node_ids, f"Missing node: {expected}"

    def test_all_17_edges_present(self, agent_spec):
        """All 17 expected edges are present."""
        assert len(agent_spec["graph"]["edges"]) == 17, (
            f"Expected 17 edges, got {len(agent_spec['graph']['edges'])}"
        )


class TestAgentQAPipelineGoal:
    """Test the goal definition of the Agent QA Pipeline."""

    def test_goal_has_success_criteria(self, agent_spec):
        """Goal has success criteria defined."""
        goal = agent_spec["goal"]
        assert "success_criteria" in goal
        assert len(goal["success_criteria"]) >= 5

    def test_goal_has_constraints(self, agent_spec):
        """Goal has constraints defined."""
        goal = agent_spec["goal"]
        assert "constraints" in goal
        assert len(goal["constraints"]) >= 3

    def test_success_criteria_weights_sum_to_one(self, agent_spec):
        """Success criteria weights sum to approximately 1.0."""
        goal = agent_spec["goal"]
        total_weight = sum(sc.get("weight", 0) for sc in goal["success_criteria"])
        assert 0.9 <= total_weight <= 1.1, (
            f"Weights sum to {total_weight}, expected ~1.0"
        )
