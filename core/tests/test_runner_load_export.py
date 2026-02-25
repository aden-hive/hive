"""Tests for load_agent_export validation and error handling."""

import json
import pytest

from framework.runner.runner import load_agent_export


def test_load_agent_export_valid_minimal():
    """Valid minimal export loads without error."""
    data = {
        "graph": {
            "nodes": [
                {"id": "n1", "name": "Node 1", "description": "First node"},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n1"},
            ],
        },
        "goal": {"success_criteria": [], "constraints": []},
    }
    graph, goal = load_agent_export(data)
    assert graph.id == "agent-graph"
    assert len(graph.nodes) == 1
    assert len(graph.edges) == 1
    assert goal.id == ""


def test_load_agent_export_from_json_string():
    """Valid JSON string is parsed and loaded."""
    data = json.dumps({
        "graph": {
            "nodes": [{"id": "n1", "name": "N1", "description": "D1"}],
            "edges": [{"id": "e1", "source": "n1", "target": "n1"}],
        },
        "goal": {"success_criteria": [], "constraints": []},
    })
    graph, goal = load_agent_export(data)
    assert len(graph.nodes) == 1


def test_load_agent_export_invalid_json_raises():
    """Invalid JSON string raises ValueError with clear message."""
    with pytest.raises(ValueError, match="Invalid agent export JSON"):
        load_agent_export("{ invalid }")


def test_load_agent_export_missing_edge_id_raises():
    """Missing required edge key raises ValueError."""
    data = {
        "graph": {
            "nodes": [{"id": "n1", "name": "N1", "description": "D1"}],
            "edges": [{"source": "n1", "target": "n1"}],  # missing "id"
        },
        "goal": {"success_criteria": [], "constraints": []},
    }
    with pytest.raises(ValueError, match="missing required key 'id'"):
        load_agent_export(data)


def test_load_agent_export_missing_success_criterion_description_raises():
    """Missing required success_criteria description raises ValueError."""
    data = {
        "graph": {
            "nodes": [{"id": "n1", "name": "N1", "description": "D1"}],
            "edges": [],
        },
        "goal": {
            "success_criteria": [{"id": "sc1"}],  # missing "description"
            "constraints": [],
        },
    }
    with pytest.raises(ValueError, match="missing required key 'description'"):
        load_agent_export(data)


def test_load_agent_export_non_dict_raises():
    """Non-dict root raises ValueError."""
    with pytest.raises(ValueError, match="expected dict or JSON object"):
        load_agent_export([1, 2, 3])
