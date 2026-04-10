"""Tests for framework/tools/flowchart_utils.py."""

import json
from types import SimpleNamespace

from framework.tools.flowchart_utils import (
    FLOWCHART_FILENAME,
    FLOWCHART_TYPES,
    classify_flowchart_node,
    generate_fallback_flowchart,
    load_flowchart_file,
    save_flowchart_file,
    synthesize_draft_from_runtime,
)


def _make_node(
    id,
    name="Node",
    description="",
    node_type="event_loop",
    tools=None,
    input_keys=None,
    output_keys=None,
    success_criteria="",
    sub_agents=None,
):
    """Create a minimal node-like object matching NodeSpec interface."""
    return SimpleNamespace(
        id=id,
        name=name,
        description=description,
        node_type=node_type,
        tools=tools or [],
        input_keys=input_keys or [],
        output_keys=output_keys or [],
        success_criteria=success_criteria,
        sub_agents=sub_agents or [],
    )


def _make_edge(source, target, condition="on_success", description=""):
    """Create a minimal edge-like object matching EdgeSpec interface."""
    return SimpleNamespace(
        source=source,
        target=target,
        condition=SimpleNamespace(value=condition),
        description=description,
    )


def _make_goal(
    name="Test Goal", description="A test goal", success_criteria=None, constraints=None
):
    """Create a minimal goal-like object matching Goal interface."""
    return SimpleNamespace(
        name=name,
        description=description,
        success_criteria=success_criteria or [],
        constraints=constraints or [],
    )


def _make_graph(nodes, edges, entry_node=None, terminal_nodes=None):
    """Create a minimal graph-like object matching GraphSpec interface."""
    return SimpleNamespace(
        nodes=nodes,
        edges=edges,
        entry_node=entry_node or (nodes[0].id if nodes else ""),
        terminal_nodes=terminal_nodes or [],
    )


class TestClassifyFlowchartNode:
    """Test flowchart node classification logic."""

    def test_first_node_is_start(self):
        node = {"id": "n1", "node_type": "event_loop", "tools": []}
        result = classify_flowchart_node(node, 0, 3, [], set())
        assert result == "start"

    def test_terminal_node(self):
        node = {"id": "n3", "node_type": "event_loop", "tools": []}
        edges = [{"source": "n1", "target": "n3"}]
        result = classify_flowchart_node(node, 2, 3, edges, {"n3"})
        assert result == "terminal"

    def test_subprocess_node(self):
        node = {"id": "n2", "node_type": "event_loop", "tools": [], "sub_agents": ["sub1"]}
        edges = [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"}]
        result = classify_flowchart_node(node, 1, 3, edges, set())
        assert result == "subprocess"

    def test_default_is_process(self):
        node = {"id": "n2", "node_type": "event_loop", "tools": [], "description": "do stuff"}
        edges = [{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n3"}]
        result = classify_flowchart_node(node, 1, 3, edges, set())
        assert result == "process"

    def test_explicit_override(self):
        node = {"id": "n2", "node_type": "event_loop", "tools": [], "flowchart_type": "database"}
        edges = [{"source": "n1", "target": "n2"}]
        result = classify_flowchart_node(node, 1, 3, edges, set())
        assert result == "database"

    def test_decision_node_with_branching(self):
        node = {"id": "n2", "node_type": "event_loop", "tools": []}
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3", "condition": "on_success"},
            {"source": "n2", "target": "n4", "condition": "on_failure"},
        ]
        result = classify_flowchart_node(node, 1, 4, edges, set())
        assert result == "decision"


class TestSynthesizeDraftFromRuntime:
    """Test runtime graph to DraftGraph conversion."""

    def test_basic_linear_graph(self):
        nodes = [
            _make_node("intake", "Intake"),
            _make_node("process", "Process"),
            _make_node("deliver", "Deliver"),
        ]
        edges = [
            _make_edge("intake", "process"),
            _make_edge("process", "deliver"),
        ]
        draft, fmap = synthesize_draft_from_runtime(
            nodes, edges, agent_name="test_agent", goal_name="Test"
        )

        assert draft["agent_name"] == "test_agent"
        assert draft["goal"] == "Test"
        assert len(draft["nodes"]) == 3
        assert len(draft["edges"]) == 2
        assert draft["entry_node"] == "intake"
        assert "deliver" in draft["terminal_nodes"]

        # First node should be start type
        assert draft["nodes"][0]["flowchart_type"] == "start"
        # Last node (terminal) should be terminal type
        assert draft["nodes"][2]["flowchart_type"] == "terminal"
        # Middle node should be process
        assert draft["nodes"][1]["flowchart_type"] == "process"

        # All nodes should have shape and color
        for node in draft["nodes"]:
            assert "flowchart_shape" in node
            assert "flowchart_color" in node

        # Flowchart map should be identity
        assert fmap == {"intake": ["intake"], "process": ["process"], "deliver": ["deliver"]}

        # Legend should contain all types
        assert draft["flowchart_legend"] == {
            k: {"shape": v["shape"], "color": v["color"]} for k, v in FLOWCHART_TYPES.items()
        }

    def test_graph_with_sub_agents(self):
        nodes = [
            _make_node("main", "Main", sub_agents=["helper"]),
            _make_node("helper", "Helper"),
        ]
        edges = [_make_edge("main", "helper")]
        draft, fmap = synthesize_draft_from_runtime(nodes, edges)

        # Sub-agent edges should be added
        assert len(draft["edges"]) > 1

        # Helper should be grouped under main in the flowchart map
        assert "helper" not in fmap
        assert fmap["main"] == ["main", "helper"]


class TestFlowchartFilePersistence:
    """Test save/load of flowchart.json."""

    def test_save_and_load(self, tmp_path):
        draft = {"agent_name": "test", "nodes": [], "edges": []}
        fmap = {"n1": ["n1"]}

        save_flowchart_file(tmp_path, draft, fmap)
        loaded_draft, loaded_map = load_flowchart_file(tmp_path)

        assert loaded_draft == draft
        assert loaded_map == fmap

    def test_load_missing_file(self, tmp_path):
        draft, fmap = load_flowchart_file(tmp_path)
        assert draft is None
        assert fmap is None

    def test_load_none_path(self):
        draft, fmap = load_flowchart_file(None)
        assert draft is None
        assert fmap is None

    def test_save_none_path(self):
        # Should not raise
        save_flowchart_file(None, {}, {})


class TestGenerateFallbackFlowchart:
    """Test the main entry point for fallback generation."""

    def test_generates_file_when_missing(self, tmp_path):
        nodes = [
            _make_node("n1", "Start Node"),
            _make_node("n2", "End Node"),
        ]
        edges = [_make_edge("n1", "n2")]
        graph = _make_graph(nodes, edges, entry_node="n1", terminal_nodes=["n2"])
        goal = _make_goal()

        generate_fallback_flowchart(graph, goal, tmp_path)

        flowchart_path = tmp_path / FLOWCHART_FILENAME
        assert flowchart_path.exists()

        data = json.loads(flowchart_path.read_text())
        assert data["original_draft"]["agent_name"] == tmp_path.name
        assert data["original_draft"]["goal"] == "A test goal"
        assert data["flowchart_map"] is not None
        # Entry/terminal from GraphSpec should be used
        assert data["original_draft"]["entry_node"] == "n1"
        assert "n2" in data["original_draft"]["terminal_nodes"]

    def test_skips_when_file_exists(self, tmp_path):
        # Pre-create a flowchart.json
        existing = {"original_draft": {"agent_name": "existing"}, "flowchart_map": {}}
        (tmp_path / FLOWCHART_FILENAME).write_text(json.dumps(existing))

        nodes = [_make_node("n1", "Node")]
        graph = _make_graph(nodes, [], entry_node="n1")
        goal = _make_goal()

        generate_fallback_flowchart(graph, goal, tmp_path)

        # Should not have been overwritten
        data = json.loads((tmp_path / FLOWCHART_FILENAME).read_text())
        assert data["original_draft"]["agent_name"] == "existing"

    def test_handles_errors_gracefully(self, tmp_path):
        # Pass an invalid path (file, not directory)
        fake_path = tmp_path / "not_a_dir.txt"
        fake_path.write_text("hello")

        graph = _make_graph([], [])
        goal = _make_goal()

        # Should not raise
        generate_fallback_flowchart(graph, goal, fake_path)

    def test_enriches_with_goal_metadata(self, tmp_path):
        nodes = [_make_node("n1", "Node")]
        graph = _make_graph(nodes, [], entry_node="n1")
        goal = _make_goal(
            description="Find bugs",
            success_criteria=[SimpleNamespace(description="All bugs found")],
            constraints=[SimpleNamespace(description="No false positives")],
        )

        generate_fallback_flowchart(graph, goal, tmp_path)

        data = json.loads((tmp_path / FLOWCHART_FILENAME).read_text())
        assert data["original_draft"]["goal"] == "Find bugs"
        assert data["original_draft"]["success_criteria"] == ["All bugs found"]
        assert data["original_draft"]["constraints"] == ["No false positives"]
