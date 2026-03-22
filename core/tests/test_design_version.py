"""Tests for design version schemas — creation, checksum, lifecycle transitions."""

import pytest

from framework.schemas.design_version import (
    DesignLifecycleState,
    DesignVersion,
    DesignVersionIndex,
    DesignVersionSummary,
)


def _sample_graph_spec() -> dict:
    return {
        "id": "test-graph",
        "goal_id": "test-goal",
        "version": "1.0.0",
        "entry_node": "start",
        "terminal_nodes": ["end"],
        "nodes": [
            {"id": "start", "name": "Start", "description": "Entry", "node_type": "event_loop"},
            {"id": "end", "name": "End", "description": "Exit", "node_type": "event_loop"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "end", "condition": "on_success"},
        ],
    }


def _sample_goal() -> dict:
    return {
        "id": "test-goal",
        "name": "Test Goal",
        "description": "A test goal",
        "success_criteria": [],
        "constraints": [],
    }


class TestDesignVersionCreate:
    def test_create_generates_id_and_timestamp(self):
        version = DesignVersion.create(
            graph_spec=_sample_graph_spec(),
            goal=_sample_goal(),
            description="test version",
        )
        assert version.version_id.startswith("v_")
        assert version.created_at
        assert version.description == "test version"
        assert version.lifecycle_state == DesignLifecycleState.DRAFT

    def test_create_computes_checksum(self):
        version = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        assert version.checksum
        assert len(version.checksum) == 16

    def test_checksum_deterministic(self):
        gs = _sample_graph_spec()
        g = _sample_goal()
        v1 = DesignVersion.create(graph_spec=gs, goal=g)
        v2 = DesignVersion.create(graph_spec=gs, goal=g)
        assert v1.checksum == v2.checksum

    def test_checksum_changes_with_different_graph(self):
        gs1 = _sample_graph_spec()
        gs2 = _sample_graph_spec()
        gs2["entry_node"] = "different"
        g = _sample_goal()
        v1 = DesignVersion.create(graph_spec=gs1, goal=g)
        v2 = DesignVersion.create(graph_spec=gs2, goal=g)
        assert v1.checksum != v2.checksum

    def test_verify_passes_for_valid_version(self):
        version = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        assert version.verify() is True

    def test_verify_fails_for_tampered_version(self):
        version = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        version.graph_spec["entry_node"] = "tampered"
        assert version.verify() is False

    def test_create_with_parent_version(self):
        version = DesignVersion.create(
            graph_spec=_sample_graph_spec(),
            goal=_sample_goal(),
            parent_version_id="v_20260321_000000_parent01",
        )
        assert version.parent_version_id == "v_20260321_000000_parent01"

    def test_create_with_flowchart(self):
        fc = {"nodes": [], "edges": [], "entry_node": "start"}
        version = DesignVersion.create(
            graph_spec=_sample_graph_spec(), goal=_sample_goal(), flowchart=fc
        )
        assert version.flowchart == fc


class TestDesignLifecycleState:
    def test_all_states_exist(self):
        assert DesignLifecycleState.DRAFT == "draft"
        assert DesignLifecycleState.CANDIDATE == "candidate"
        assert DesignLifecycleState.VALIDATED == "validated"
        assert DesignLifecycleState.PROMOTED == "promoted"
        assert DesignLifecycleState.ARCHIVED == "archived"


class TestDesignVersionSummary:
    def test_from_version(self):
        version = DesignVersion.create(
            graph_spec=_sample_graph_spec(), goal=_sample_goal(), description="test"
        )
        summary = DesignVersionSummary.from_version(version)
        assert summary.version_id == version.version_id
        assert summary.lifecycle_state == version.lifecycle_state
        assert summary.checksum == version.checksum


class TestDesignVersionIndex:
    def test_add_version(self):
        index = DesignVersionIndex(agent_id="test-agent")
        version = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        index.add_version(version)
        assert index.total_versions == 1
        assert index.latest_version_id == version.version_id

    def test_add_promoted_version_updates_current(self):
        index = DesignVersionIndex(agent_id="test-agent")
        version = DesignVersion.create(
            graph_spec=_sample_graph_spec(),
            goal=_sample_goal(),
            lifecycle_state=DesignLifecycleState.PROMOTED,
        )
        index.add_version(version)
        assert index.current_promoted_id == version.version_id

    def test_add_non_promoted_does_not_update_current(self):
        index = DesignVersionIndex(agent_id="test-agent")
        version = DesignVersion.create(
            graph_spec=_sample_graph_spec(),
            goal=_sample_goal(),
            lifecycle_state=DesignLifecycleState.CANDIDATE,
        )
        index.add_version(version)
        assert index.current_promoted_id is None

    def test_get_version_summary(self):
        index = DesignVersionIndex(agent_id="test-agent")
        version = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        index.add_version(version)
        summary = index.get_version_summary(version.version_id)
        assert summary is not None
        assert summary.version_id == version.version_id

    def test_get_version_summary_not_found(self):
        index = DesignVersionIndex(agent_id="test-agent")
        assert index.get_version_summary("v_nonexistent") is None

    def test_filter_by_state(self):
        index = DesignVersionIndex(agent_id="test-agent")
        v1 = DesignVersion.create(
            graph_spec=_sample_graph_spec(),
            goal=_sample_goal(),
            lifecycle_state=DesignLifecycleState.DRAFT,
        )
        v2 = DesignVersion.create(
            graph_spec=_sample_graph_spec(),
            goal=_sample_goal(),
            lifecycle_state=DesignLifecycleState.CANDIDATE,
        )
        index.add_version(v1)
        index.add_version(v2)
        drafts = index.filter_by_state(DesignLifecycleState.DRAFT)
        assert len(drafts) == 1

    def test_get_starred(self):
        index = DesignVersionIndex(agent_id="test-agent")
        v1 = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        v1.starred = True
        v2 = DesignVersion.create(graph_spec=_sample_graph_spec(), goal=_sample_goal())
        index.add_version(v1)
        index.add_version(v2)
        starred = index.get_starred()
        assert len(starred) == 1

    def test_empty_graph_and_goal(self):
        version = DesignVersion.create(graph_spec={}, goal={})
        assert version.checksum
        assert version.verify() is True


# === CLI REGISTRATION ===


class TestVersionCLI:
    def test_version_list_subcommand_registers(self):
        """Verify version-list subcommand is registered without errors."""
        import argparse

        from framework.runner.cli import register_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_commands(subparsers)
        args = parser.parse_args(["version-list", "/tmp/fake-agent"])
        assert hasattr(args, "func")

    def test_version_show_subcommand_registers(self):
        """Verify version-show subcommand is registered without errors."""
        import argparse

        from framework.runner.cli import register_commands

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_commands(subparsers)
        args = parser.parse_args(["version-show", "/tmp/fake-agent", "v_test"])
        assert hasattr(args, "func")
