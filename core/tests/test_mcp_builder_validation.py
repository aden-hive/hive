"""Tests for MCP agent builder validation-before-persist logic.

Verifies that add_node() does NOT persist invalid nodes to the session,
and that _load_session() handles corrupt JSON gracefully.
"""

import json

import pytest


@pytest.fixture(autouse=True)
def _isolate_sessions(tmp_path, monkeypatch):
    """Redirect SESSIONS_DIR to a temp directory for test isolation."""
    import framework.mcp.agent_builder_server as srv

    monkeypatch.setattr(srv, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(srv, "ACTIVE_SESSION_FILE", tmp_path / "sessions" / ".active")
    # Reset global session between tests
    monkeypatch.setattr(srv, "_session", None)
    yield


@pytest.fixture
def _active_session():
    """Create and activate a fresh build session."""
    import framework.mcp.agent_builder_server as srv

    session = srv.BuildSession(name="test-agent", session_id="test_session_001")
    srv._session = session
    srv._save_session(session)
    return session


# ── add_node validation-before-persist ──────────────────────────


class TestAddNodeValidationOrder:
    """Ensure invalid nodes are NOT appended to session.nodes."""

    def test_valid_node_is_persisted(self, _active_session):
        """A fully valid node should be appended and saved."""
        import framework.mcp.agent_builder_server as srv

        result_json = srv.add_node(
            node_id="planner",
            name="Planner",
            description="Plans tasks",
            node_type="event_loop",
            system_prompt="You are a planner.",
            input_keys='["query"]',
            output_keys='["plan"]',
        )
        result = json.loads(result_json)

        assert result["valid"] is True
        assert result["total_nodes"] == 1
        assert len(result["errors"]) == 0

        # Verify persisted to disk
        reloaded = srv._load_session("test_session_001")
        assert len(reloaded.nodes) == 1
        assert reloaded.nodes[0].id == "planner"

    def test_invalid_node_not_persisted(self, _active_session):
        """A node with validation errors must NOT be saved to the session."""
        import framework.mcp.agent_builder_server as srv

        # router node without routes — this is a validation error
        result_json = srv.add_node(
            node_id="bad_router",
            name="Bad Router",
            description="Missing routes",
            node_type="router",
            system_prompt="Route things.",
            input_keys='["query"]',
            output_keys='["result"]',
        )
        result = json.loads(result_json)

        assert result["valid"] is False
        assert any("must specify routes" in e for e in result["errors"])
        # Node count should be 0 — not persisted
        assert result["total_nodes"] == 0

        # Verify NOT on disk
        reloaded = srv._load_session("test_session_001")
        assert len(reloaded.nodes) == 0

    def test_invalid_nullable_keys_not_persisted(self, _active_session):
        """nullable_output_keys not in output_keys should block persistence."""
        import framework.mcp.agent_builder_server as srv

        result_json = srv.add_node(
            node_id="bad_nullable",
            name="Bad Nullable",
            description="Has invalid nullable keys",
            node_type="event_loop",
            system_prompt="Test.",
            input_keys="[]",
            output_keys='["result"]',
            nullable_output_keys='["nonexistent_key"]',
        )
        result = json.loads(result_json)

        assert result["valid"] is False
        assert any("nullable_output_keys" in e for e in result["errors"])
        assert result["total_nodes"] == 0

    def test_valid_then_invalid_preserves_only_valid(self, _active_session):
        """After adding a valid node, an invalid one should not corrupt state."""
        import framework.mcp.agent_builder_server as srv

        # Add valid node first
        srv.add_node(
            node_id="good",
            name="Good Node",
            description="Works",
            node_type="event_loop",
            system_prompt="Hello.",
            input_keys="[]",
            output_keys='["result"]',
        )

        # Add invalid node (router without routes)
        result_json = srv.add_node(
            node_id="bad",
            name="Bad Node",
            description="Broken",
            node_type="router",
            system_prompt="Route.",
            input_keys="[]",
            output_keys="[]",
        )
        result = json.loads(result_json)

        assert result["valid"] is False
        # Only the valid node should be counted
        assert result["total_nodes"] == 1

        reloaded = srv._load_session("test_session_001")
        assert len(reloaded.nodes) == 1
        assert reloaded.nodes[0].id == "good"


# ── _load_session corrupt JSON handling ─────────────────────────


class TestLoadSessionCorruptJSON:
    """Ensure _load_session raises ValueError on corrupt JSON, not raw JSONDecodeError."""

    def test_corrupt_json_raises_value_error(self, _active_session):
        """Corrupt session file should raise ValueError with descriptive message."""
        import framework.mcp.agent_builder_server as srv

        # Corrupt the session file
        session_file = srv.SESSIONS_DIR / "test_session_001.json"
        session_file.write_text("{invalid json!!!", encoding="utf-8")

        with pytest.raises(ValueError, match="corrupted data"):
            srv._load_session("test_session_001")

    def test_missing_session_raises_value_error(self):
        """Non-existent session should raise ValueError."""
        import framework.mcp.agent_builder_server as srv

        with pytest.raises(ValueError, match="not found"):
            srv._load_session("does_not_exist")
