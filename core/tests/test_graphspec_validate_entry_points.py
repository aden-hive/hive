"""Tests for GraphSpec.validate() entry-point validation.

Covers the fix for the bug where ``GraphSpec.validate()`` did not verify
that every value in ``entry_points`` references an existing node, so an
invalid resume entry point passed validation and only failed at runtime.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework.orchestrator.edge import GraphSpec


def _node(node_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=node_id,
        node_type="default",
        output_keys=[],
        client_facing=False,
    )


def _graph(entry_points: dict[str, str] | None = None) -> GraphSpec:
    nodes = [_node("start"), _node("end")]
    return GraphSpec(
        id="test-graph",
        goal_id="goal-1",
        entry_node="start",
        entry_points=entry_points or {},
        terminal_nodes=["end"],
        nodes=nodes,
        edges=[],
    )


def test_valid_entry_point_passes_validation():
    graph = _graph(entry_points={"resume": "end"})
    result = graph.validate()
    assert not any("references missing node" in e for e in result["errors"])


def test_missing_entry_point_target_reported():
    graph = _graph(entry_points={"resume": "missing_node"})
    result = graph.validate()
    assert "Entry point 'resume' references missing node 'missing_node'" in result["errors"]


def test_mixed_valid_and_invalid_entry_points():
    graph = _graph(entry_points={"resume": "end", "alt": "ghost"})
    result = graph.validate()
    assert "Entry point 'alt' references missing node 'ghost'" in result["errors"]
    # The valid entry point must not produce an error.
    assert not any("'resume'" in e for e in result["errors"])
