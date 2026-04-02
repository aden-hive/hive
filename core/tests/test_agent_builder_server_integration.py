"""
Integration tests for the MCP Agent Builder Server.

Tests the MCP API layer including session lifecycle, graph operations,
validation logic, and error handling.
"""

import json

import pytest

# Skip all tests if MCP dependencies are not installed
try:
    import mcp  # noqa: F401
    from mcp.server import FastMCP  # noqa: F401

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP dependencies not installed")


@pytest.fixture
def mock_session_storage(tmp_path, monkeypatch):
    """Mock session storage to use temp directory."""
    import importlib

    # Import the module directly to bypass __init__.py that exports FastMCP object
    server = importlib.import_module("framework.mcp.agent_builder_server")

    sessions_dir = tmp_path / ".test-sessions"
    active_file = sessions_dir / ".active"

    # Use object-based setattr with the correctly imported module
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "ACTIVE_SESSION_FILE", active_file)
    monkeypatch.setattr(server, "_session", None)

    yield tmp_path


@pytest.fixture
def reset_global_session(monkeypatch):
    """Reset the global session state before each test."""
    import importlib

    server = importlib.import_module("framework.mcp.agent_builder_server")
    monkeypatch.setattr(server, "_session", None)


# =============================================================================
# SESSION LIFECYCLE TESTS
# =============================================================================


class TestSessionLifecycle:
    """Tests for session create, load, list, delete operations."""

    def test_create_session(self, mock_session_storage, reset_global_session):
        """Test creating a new session."""
        from framework.mcp.agent_builder_server import create_session

        result = json.loads(create_session(name="Test Agent"))

        assert result["status"] == "created"
        assert result["name"] == "Test Agent"
        assert result["session_id"].startswith("build_")
        assert result["persisted"] is True

    def test_create_session_generates_unique_ids(self, mock_session_storage, reset_global_session):
        """Test that multiple sessions get unique IDs."""
        import time

        from framework.mcp.agent_builder_server import create_session

        result1 = json.loads(create_session(name="Agent 1"))
        # Sleep to ensure different timestamp (IDs use second precision)
        time.sleep(1.1)
        result2 = json.loads(create_session(name="Agent 2"))

        assert result1["session_id"] != result2["session_id"]

    def test_list_sessions_empty(self, mock_session_storage, reset_global_session):
        """Test listing sessions when none exist."""
        from framework.mcp.agent_builder_server import list_sessions

        result = json.loads(list_sessions())

        assert result["sessions"] == []
        assert result["total"] == 0
        assert result["active_session_id"] is None

    def test_list_sessions_with_data(self, mock_session_storage, reset_global_session):
        """Test listing sessions after creating some."""
        import time

        from framework.mcp.agent_builder_server import create_session, list_sessions

        create_session(name="Agent 1")
        # Sleep to ensure different session ID (uses second precision timestamp)
        time.sleep(1.1)
        create_session(name="Agent 2")

        result = json.loads(list_sessions())

        assert result["total"] == 2
        assert len(result["sessions"]) == 2
        names = [s["name"] for s in result["sessions"]]
        assert "Agent 1" in names
        assert "Agent 2" in names

    def test_load_session_by_id(self, mock_session_storage, reset_global_session):
        """Test loading an existing session by ID."""
        from framework.mcp.agent_builder_server import (
            create_session,
            load_session_by_id,
        )

        create_result = json.loads(create_session(name="My Agent"))
        session_id = create_result["session_id"]

        # Simulate process restart by resetting global session
        import framework.mcp.agent_builder_server as server

        server._session = None

        load_result = json.loads(load_session_by_id(session_id=session_id))

        assert load_result["success"] is True
        assert load_result["session_id"] == session_id
        assert load_result["name"] == "My Agent"

    def test_load_session_not_found(self, mock_session_storage, reset_global_session):
        """Test loading a non-existent session."""
        from framework.mcp.agent_builder_server import load_session_by_id

        result = json.loads(load_session_by_id(session_id="nonexistent_session"))

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_delete_session(self, mock_session_storage, reset_global_session):
        """Test deleting a session."""
        from framework.mcp.agent_builder_server import (
            create_session,
            delete_session,
            list_sessions,
        )

        create_result = json.loads(create_session(name="To Delete"))
        session_id = create_result["session_id"]

        delete_result = json.loads(delete_session(session_id=session_id))
        assert delete_result["success"] is True
        assert delete_result["deleted_session_id"] == session_id

        list_result = json.loads(list_sessions())
        assert list_result["total"] == 0

    def test_delete_session_not_found(self, mock_session_storage, reset_global_session):
        """Test deleting a non-existent session."""
        from framework.mcp.agent_builder_server import delete_session

        result = json.loads(delete_session(session_id="nonexistent"))

        assert result["success"] is False
        assert "not found" in result["error"].lower()


# =============================================================================
# GOAL MANAGEMENT TESTS
# =============================================================================


class TestGoalManagement:
    """Tests for goal setting and validation."""

    def test_set_goal_valid(self, mock_session_storage, reset_global_session):
        """Test setting a valid goal."""
        from framework.mcp.agent_builder_server import create_session, set_goal

        create_session(name="Test Agent")

        criteria = json.dumps(
            [{"id": "sc1", "description": "Task completed successfully", "weight": 1.0}]
        )
        constraints = json.dumps([{"id": "c1", "description": "Must not exceed rate limits"}])

        result = json.loads(
            set_goal(
                goal_id="goal_1",
                name="Complete Task",
                description="Execute the task successfully",
                success_criteria=criteria,
                constraints=constraints,
            )
        )

        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["goal"]["id"] == "goal_1"
        assert result["goal"]["name"] == "Complete Task"

    def test_set_goal_invalid_json(self, mock_session_storage, reset_global_session):
        """Test handling malformed JSON in success_criteria."""
        from framework.mcp.agent_builder_server import create_session, set_goal

        create_session(name="Test Agent")

        result = json.loads(
            set_goal(
                goal_id="goal_1",
                name="Test",
                description="Test",
                success_criteria="invalid json [",
            )
        )

        assert result["valid"] is False
        assert any("Invalid JSON" in e for e in result["errors"])

    def test_set_goal_missing_fields(self, mock_session_storage, reset_global_session):
        """Test validation of required fields."""
        from framework.mcp.agent_builder_server import create_session, set_goal

        create_session(name="Test Agent")

        # Missing id in success criteria
        criteria = json.dumps([{"description": "No id provided"}])

        result = json.loads(
            set_goal(
                goal_id="goal_1",
                name="Test",
                description="Test",
                success_criteria=criteria,
            )
        )

        assert result["valid"] is False
        assert any("missing required field 'id'" in e for e in result["errors"])

    def test_set_goal_empty_criteria(self, mock_session_storage, reset_global_session):
        """Test rejection of empty success criteria."""
        from framework.mcp.agent_builder_server import create_session, set_goal

        create_session(name="Test Agent")

        result = json.loads(
            set_goal(
                goal_id="goal_1",
                name="Test",
                description="Test",
                success_criteria="[]",
            )
        )

        assert result["valid"] is False
        assert any("at least one success criterion" in e for e in result["errors"])

    def test_set_goal_no_session(self, mock_session_storage, reset_global_session):
        """Test setting goal without active session raises error."""
        from framework.mcp.agent_builder_server import set_goal

        with pytest.raises(ValueError, match="No active session"):
            set_goal(
                goal_id="goal_1",
                name="Test",
                description="Test",
                success_criteria='[{"id": "sc1", "description": "test"}]',
            )


# =============================================================================
# NODE OPERATIONS TESTS
# =============================================================================


class TestNodeOperations:
    """Tests for node add, update, delete operations."""

    def _create_session_with_goal(self):
        """Helper to create a session with a goal."""
        from framework.mcp.agent_builder_server import create_session, set_goal

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test Goal",
            description="Test goal description",
            success_criteria='[{"id": "sc1", "description": "Test criterion"}]',
        )

    def test_add_node_valid(self, mock_session_storage, reset_global_session):
        """Test adding a valid node."""
        from framework.mcp.agent_builder_server import add_node, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_node(
                node_id="node_1",
                name="Process Node",
                description="Processes input data",
                node_type="llm_generate",
                input_keys='["input"]',
                output_keys='["output"]',
                system_prompt="You are a helpful assistant.",
            )
        )

        assert result["valid"] is True
        assert result["node"]["id"] == "node_1"
        assert result["node"]["name"] == "Process Node"
        assert result["total_nodes"] == 1

    def test_add_node_duplicate_id(self, mock_session_storage, reset_global_session):
        """Test rejection of duplicate node IDs."""
        from framework.mcp.agent_builder_server import add_node, create_session

        create_session(name="Test Agent")

        add_node(
            node_id="node_1",
            name="First Node",
            description="First",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        result = json.loads(
            add_node(
                node_id="node_1",
                name="Duplicate Node",
                description="Duplicate",
                node_type="llm_generate",
                input_keys="[]",
                output_keys="[]",
            )
        )

        assert result["valid"] is False
        assert any("already exists" in e for e in result["errors"])

    def test_add_node_tool_use_without_tools(self, mock_session_storage, reset_global_session):
        """Test that llm_tool_use nodes require tools."""
        from framework.mcp.agent_builder_server import add_node, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_node(
                node_id="node_1",
                name="Tool Node",
                description="Uses tools",
                node_type="llm_tool_use",
                input_keys="[]",
                output_keys="[]",
                tools="[]",  # Empty tools
            )
        )

        assert result["valid"] is False
        assert any("must specify tools" in e for e in result["errors"])

    def test_add_node_router_without_routes(self, mock_session_storage, reset_global_session):
        """Test that router nodes require routes."""
        from framework.mcp.agent_builder_server import add_node, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_node(
                node_id="router_1",
                name="Router",
                description="Routes traffic",
                node_type="router",
                input_keys="[]",
                output_keys="[]",
                routes="{}",  # Empty routes
            )
        )

        assert result["valid"] is False
        assert any("must specify routes" in e for e in result["errors"])

    def test_update_node(self, mock_session_storage, reset_global_session):
        """Test updating an existing node."""
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            update_node,
        )

        create_session(name="Test Agent")
        add_node(
            node_id="node_1",
            name="Original Name",
            description="Original",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
            system_prompt="Original prompt",
        )

        result = json.loads(update_node(node_id="node_1", name="Updated Name"))

        assert result["valid"] is True
        assert result["node"]["name"] == "Updated Name"

    def test_update_node_not_found(self, mock_session_storage, reset_global_session):
        """Test updating a non-existent node."""
        from framework.mcp.agent_builder_server import create_session, update_node

        create_session(name="Test Agent")

        result = json.loads(update_node(node_id="nonexistent", name="New Name"))

        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_delete_node(self, mock_session_storage, reset_global_session):
        """Test deleting a node."""
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            delete_node,
            get_session,
        )

        create_session(name="Test Agent")
        add_node(
            node_id="node_1",
            name="To Delete",
            description="Delete me",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        result = json.loads(delete_node(node_id="node_1"))

        # API returns "valid", not "success"
        assert result["valid"] is True
        assert len(get_session().nodes) == 0


# =============================================================================
# EDGE OPERATIONS TESTS
# =============================================================================


class TestEdgeOperations:
    """Tests for edge add, delete operations."""

    def _setup_nodes(self):
        """Helper to create a session with two nodes."""
        from framework.mcp.agent_builder_server import add_node, create_session

        create_session(name="Test Agent")
        add_node(
            node_id="node_a",
            name="Node A",
            description="First node",
            node_type="llm_generate",
            input_keys="[]",
            output_keys='["result"]',
        )
        add_node(
            node_id="node_b",
            name="Node B",
            description="Second node",
            node_type="llm_generate",
            input_keys='["result"]',
            output_keys="[]",
        )

    def test_add_edge_valid(self, mock_session_storage, reset_global_session):
        """Test adding a valid edge."""
        from framework.mcp.agent_builder_server import add_edge

        self._setup_nodes()

        result = json.loads(
            add_edge(
                edge_id="edge_1",
                source="node_a",
                target="node_b",
                condition="on_success",
            )
        )

        assert result["valid"] is True
        assert result["edge"]["source"] == "node_a"
        assert result["edge"]["target"] == "node_b"
        assert result["total_edges"] == 1

    def test_add_edge_missing_source(self, mock_session_storage, reset_global_session):
        """Test rejection of edge with non-existent source."""
        from framework.mcp.agent_builder_server import add_edge

        self._setup_nodes()

        result = json.loads(
            add_edge(
                edge_id="edge_1",
                source="nonexistent",
                target="node_b",
            )
        )

        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_add_edge_missing_target(self, mock_session_storage, reset_global_session):
        """Test rejection of edge with non-existent target."""
        from framework.mcp.agent_builder_server import add_edge

        self._setup_nodes()

        result = json.loads(
            add_edge(
                edge_id="edge_1",
                source="node_a",
                target="nonexistent",
            )
        )

        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_add_edge_conditional_without_expr(self, mock_session_storage, reset_global_session):
        """Test that conditional edges require condition_expr."""
        from framework.mcp.agent_builder_server import add_edge

        self._setup_nodes()

        result = json.loads(
            add_edge(
                edge_id="edge_1",
                source="node_a",
                target="node_b",
                condition="conditional",
                condition_expr="",  # Empty expression
            )
        )

        assert result["valid"] is False
        assert any("needs condition_expr" in e for e in result["errors"])

    def test_add_edge_duplicate_id(self, mock_session_storage, reset_global_session):
        """Test rejection of duplicate edge IDs."""
        from framework.mcp.agent_builder_server import add_edge

        self._setup_nodes()

        add_edge(edge_id="edge_1", source="node_a", target="node_b")

        result = json.loads(add_edge(edge_id="edge_1", source="node_a", target="node_b"))

        assert result["valid"] is False
        assert any("already exists" in e for e in result["errors"])

    def test_delete_edge(self, mock_session_storage, reset_global_session):
        """Test deleting an edge."""
        from framework.mcp.agent_builder_server import (
            add_edge,
            delete_edge,
            get_session,
        )

        self._setup_nodes()
        add_edge(edge_id="edge_1", source="node_a", target="node_b")

        result = json.loads(delete_edge(edge_id="edge_1"))

        # API returns "valid", not "success"
        assert result["valid"] is True
        assert len(get_session().edges) == 0


# =============================================================================
# GRAPH VALIDATION TESTS
# =============================================================================


class TestGraphValidation:
    """Tests for graph validation logic."""

    def _setup_simple_graph(self):
        """Helper to create a simple valid graph."""
        from framework.mcp.agent_builder_server import (
            add_edge,
            add_node,
            create_session,
            set_goal,
        )

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test Goal",
            description="Test goal",
            success_criteria='[{"id": "sc1", "description": "Success"}]',
        )
        add_node(
            node_id="start",
            name="Start",
            description="Entry point",
            node_type="llm_generate",
            input_keys='["input"]',
            output_keys='["result"]',
            system_prompt="Process input",
        )
        add_node(
            node_id="end",
            name="End",
            description="Exit point",
            node_type="llm_generate",
            input_keys='["result"]',
            output_keys='["output"]',
            system_prompt="Format output",
        )
        add_edge(edge_id="e1", source="start", target="end")

    def test_validate_empty_graph(self, mock_session_storage, reset_global_session):
        """Test validation of graph with no nodes."""
        from framework.mcp.agent_builder_server import (
            create_session,
            set_goal,
            validate_graph,
        )

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test",
            description="Test",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )

        result = json.loads(validate_graph())

        assert result["valid"] is False
        assert any("No nodes defined" in e for e in result["errors"])

    def test_validate_no_goal(self, mock_session_storage, reset_global_session):
        """Test validation of graph without goal."""
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            validate_graph,
        )

        create_session(name="Test Agent")
        add_node(
            node_id="node_1",
            name="Node",
            description="Test",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        result = json.loads(validate_graph())

        assert result["valid"] is False
        assert any("No goal defined" in e for e in result["errors"])

    def test_validate_valid_graph(self, mock_session_storage, reset_global_session):
        """Test validation of a valid graph."""
        from framework.mcp.agent_builder_server import validate_graph

        self._setup_simple_graph()

        result = json.loads(validate_graph())

        assert result["valid"] is True
        assert result["entry_node"] == "start"
        assert "end" in result["terminal_nodes"]
        assert result["node_count"] == 2
        assert result["edge_count"] == 1

    def test_validate_unreachable_nodes(self, mock_session_storage, reset_global_session):
        """Test detection of unreachable nodes."""
        from framework.mcp.agent_builder_server import (
            add_edge,
            add_node,
            create_session,
            set_goal,
            validate_graph,
        )

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test",
            description="Test",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )
        add_node(
            node_id="start",
            name="Start",
            description="Entry",
            node_type="llm_generate",
            input_keys="[]",
            output_keys='["result"]',
        )
        add_node(
            node_id="end",
            name="End",
            description="Exit",
            node_type="llm_generate",
            input_keys='["result"]',
            output_keys="[]",
        )
        add_node(
            node_id="orphan",
            name="Orphan",
            description="Unreachable node",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )
        add_edge(edge_id="e1", source="start", target="end")

        result = json.loads(validate_graph())

        assert result["valid"] is False
        assert any("Unreachable nodes" in str(e) for e in result["errors"])

    def test_validate_context_flow(self, mock_session_storage, reset_global_session):
        """Test context flow validation (input/output key matching)."""
        from framework.mcp.agent_builder_server import (
            add_edge,
            add_node,
            create_session,
            set_goal,
            validate_graph,
        )

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test",
            description="Test",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )
        add_node(
            node_id="start",
            name="Start",
            description="Entry",
            node_type="llm_generate",
            input_keys="[]",
            output_keys='["data"]',
        )
        add_node(
            node_id="end",
            name="End",
            description="Exit",
            node_type="llm_generate",
            input_keys='["missing_key"]',  # This key is never produced
            output_keys="[]",
        )
        add_edge(edge_id="e1", source="start", target="end")

        result = json.loads(validate_graph())

        # Context flow issues generate errors about missing inputs
        assert any("missing_key" in str(e) for e in result.get("errors", []))

    def test_validate_multiple_entry_points_warning(
        self, mock_session_storage, reset_global_session
    ):
        """Test warning for multiple entry points in non-pause/resume graph."""
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            set_goal,
            validate_graph,
        )

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test",
            description="Test",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )
        # Two nodes with no incoming edges = two entry points
        add_node(
            node_id="entry1",
            name="Entry 1",
            description="First entry",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )
        add_node(
            node_id="entry2",
            name="Entry 2",
            description="Second entry",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        result = json.loads(validate_graph())

        assert any("Multiple entry candidates" in w for w in result.get("warnings", []))


# =============================================================================
# INPUT VALIDATION TESTS
# =============================================================================


class TestInputValidation:
    """Tests for invalid input handling."""

    def test_malformed_json_in_add_node(self, mock_session_storage, reset_global_session):
        """Test graceful handling of malformed JSON in add_node."""
        from framework.mcp.agent_builder_server import add_node, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_node(
                node_id="node_1",
                name="Test",
                description="Test",
                node_type="llm_generate",
                input_keys="[invalid json",
                output_keys="[]",
            )
        )

        assert result["valid"] is False
        assert any("Invalid JSON" in e for e in result["errors"])

    def test_malformed_json_in_add_edge(self, mock_session_storage, reset_global_session):
        """Test that add_edge handles invalid condition gracefully."""
        from framework.mcp.agent_builder_server import add_edge, add_node, create_session

        create_session(name="Test Agent")
        add_node(
            node_id="a",
            name="A",
            description="A",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )
        add_node(
            node_id="b",
            name="B",
            description="B",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        # Invalid condition falls back to ON_SUCCESS
        result = json.loads(
            add_edge(
                edge_id="e1",
                source="a",
                target="b",
                condition="invalid_condition",
            )
        )

        # Should succeed with default condition
        assert result["valid"] is True

    def test_no_session_raises_error(self, mock_session_storage, reset_global_session):
        """Test that operations without a session raise appropriate errors."""
        from framework.mcp.agent_builder_server import add_node

        with pytest.raises(ValueError, match="No active session"):
            add_node(
                node_id="node_1",
                name="Test",
                description="Test",
                node_type="llm_generate",
                input_keys="[]",
                output_keys="[]",
            )


# =============================================================================
# SESSION PERSISTENCE TESTS
# =============================================================================


class TestSessionPersistence:
    """Tests for session save/load functionality."""

    def test_session_survives_global_reset(self, mock_session_storage, reset_global_session):
        """Test that session data persists across global state resets."""
        import framework.mcp.agent_builder_server as server
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            load_session_by_id,
        )

        # Create session and add a node
        create_result = json.loads(create_session(name="Persistent Agent"))
        session_id = create_result["session_id"]

        add_node(
            node_id="node_1",
            name="Test Node",
            description="Test",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        # Reset global state
        server._session = None

        # Reload session
        load_result = json.loads(load_session_by_id(session_id=session_id))

        assert load_result["success"] is True
        assert load_result["node_count"] == 1

    def test_goal_persists_across_reload(self, mock_session_storage, reset_global_session):
        """Test that goal data persists when session is reloaded."""
        import framework.mcp.agent_builder_server as server
        from framework.mcp.agent_builder_server import (
            create_session,
            get_session,
            load_session_by_id,
            set_goal,
        )

        create_result = json.loads(create_session(name="Goal Test"))
        session_id = create_result["session_id"]

        set_goal(
            goal_id="goal_1",
            name="Persisted Goal",
            description="Should persist",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )

        # Reset and reload
        server._session = None
        load_session_by_id(session_id=session_id)

        session = get_session()
        assert session.goal is not None
        assert session.goal.name == "Persisted Goal"

    def test_edges_persist_with_correct_condition(self, mock_session_storage, reset_global_session):
        """Test that edge conditions are correctly serialized and deserialized."""
        import framework.mcp.agent_builder_server as server
        from framework.graph import EdgeCondition
        from framework.mcp.agent_builder_server import (
            add_edge,
            add_node,
            create_session,
            get_session,
            load_session_by_id,
        )

        create_result = json.loads(create_session(name="Edge Test"))
        session_id = create_result["session_id"]

        add_node(
            node_id="a",
            name="A",
            description="A",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )
        add_node(
            node_id="b",
            name="B",
            description="B",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )
        add_edge(edge_id="e1", source="a", target="b", condition="on_failure")

        # Reset and reload
        server._session = None
        load_session_by_id(session_id=session_id)

        session = get_session()
        assert len(session.edges) == 1
        assert session.edges[0].condition == EdgeCondition.ON_FAILURE


# =============================================================================
# MCP SERVER REGISTRATION TESTS
# =============================================================================


class TestMCPServerRegistration:
    """Tests for MCP server registration tools (add, list, remove)."""

    def test_add_mcp_server_http_missing_url(self, mock_session_storage, reset_global_session):
        """Test that http transport requires url."""
        from framework.mcp.agent_builder_server import add_mcp_server, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_mcp_server(
                name="remote-tools",
                transport="http",
                url="",  # Missing URL
            )
        )

        assert result["success"] is False
        assert any("url is required" in str(e) for e in result.get("errors", []))

    def test_add_mcp_server_stdio_missing_command(self, mock_session_storage, reset_global_session):
        """Test that stdio transport requires command."""
        from framework.mcp.agent_builder_server import add_mcp_server, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_mcp_server(
                name="local-tools",
                transport="stdio",
                command="",  # Missing command
            )
        )

        assert result["success"] is False
        assert any("command is required" in str(e) for e in result.get("errors", []))

    def test_add_mcp_server_invalid_transport(self, mock_session_storage, reset_global_session):
        """Test rejection of invalid transport type."""
        from framework.mcp.agent_builder_server import add_mcp_server, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_mcp_server(
                name="test-server",
                transport="websocket",  # Invalid
            )
        )

        assert result["success"] is False
        assert "Invalid transport" in result["error"]

    def test_add_mcp_server_invalid_json_args(self, mock_session_storage, reset_global_session):
        """Test handling of malformed JSON in args."""
        from framework.mcp.agent_builder_server import add_mcp_server, create_session

        create_session(name="Test Agent")

        result = json.loads(
            add_mcp_server(
                name="test-server",
                transport="stdio",
                command="python",
                args="[invalid json",  # Malformed
            )
        )

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_list_mcp_servers_empty(self, mock_session_storage, reset_global_session):
        """Test listing servers when none registered."""
        from framework.mcp.agent_builder_server import create_session, list_mcp_servers

        create_session(name="Test Agent")

        result = json.loads(list_mcp_servers())

        assert result["mcp_servers"] == []
        assert result["total"] == 0
        assert "No MCP servers" in result.get("note", "")

    def test_remove_mcp_server_not_found(self, mock_session_storage, reset_global_session):
        """Test removing a non-existent server."""
        from framework.mcp.agent_builder_server import (
            create_session,
            remove_mcp_server,
        )

        create_session(name="Test Agent")

        result = json.loads(remove_mcp_server(name="nonexistent"))

        assert result["success"] is False
        assert "not found" in result["error"]


# =============================================================================
# PLAN VALIDATION TESTS
# =============================================================================


class TestPlanCreation:
    """Tests for plan creation and validation."""

    def test_create_plan_valid(self, mock_session_storage, reset_global_session):
        """Test creating a valid plan."""
        from framework.mcp.agent_builder_server import create_plan

        steps = json.dumps(
            [
                {
                    "id": "step_1",
                    "description": "Fetch user data",
                    "action": {"action_type": "tool_use", "tool_name": "get_user"},
                    "inputs": {"user_id": "$input_user_id"},
                    "expected_outputs": ["user_data"],
                    "dependencies": [],
                }
            ]
        )

        result = json.loads(
            create_plan(
                plan_id="plan_1",
                goal_id="goal_1",
                description="Test plan",
                steps=steps,
            )
        )

        assert result["success"] is True
        assert result["plan"]["id"] == "plan_1"
        assert result["step_count"] == 1

    def test_create_plan_invalid_json(self, mock_session_storage, reset_global_session):
        """Test handling of malformed JSON in steps."""
        from framework.mcp.agent_builder_server import create_plan

        result = json.loads(
            create_plan(
                plan_id="plan_1",
                goal_id="goal_1",
                description="Test",
                steps="[invalid json",
            )
        )

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_create_plan_missing_step_id(self, mock_session_storage, reset_global_session):
        """Test validation of missing step ID."""
        from framework.mcp.agent_builder_server import create_plan

        steps = json.dumps(
            [
                {
                    "description": "No ID step",
                    "action": {"action_type": "llm_call"},
                }
            ]
        )

        result = json.loads(
            create_plan(
                plan_id="plan_1",
                goal_id="goal_1",
                description="Test",
                steps=steps,
            )
        )

        assert result["success"] is False
        assert any("missing 'id'" in e for e in result["errors"])

    def test_create_plan_duplicate_step_id(self, mock_session_storage, reset_global_session):
        """Test rejection of duplicate step IDs."""
        from framework.mcp.agent_builder_server import create_plan

        steps = json.dumps(
            [
                {"id": "step_1", "description": "First", "action": {"action_type": "llm_call"}},
                {"id": "step_1", "description": "Duplicate", "action": {"action_type": "llm_call"}},
            ]
        )

        result = json.loads(
            create_plan(
                plan_id="plan_1",
                goal_id="goal_1",
                description="Test",
                steps=steps,
            )
        )

        assert result["success"] is False
        assert any("Duplicate step id" in e for e in result["errors"])


class TestPlanValidation:
    """Tests for validate_plan function."""

    def test_validate_plan_missing_required_fields(
        self, mock_session_storage, reset_global_session
    ):
        """Test validation of missing required fields."""
        from framework.mcp.agent_builder_server import validate_plan

        result = json.loads(validate_plan(plan_json="{}"))

        assert result["valid"] is False
        assert any("Missing required field" in e for e in result["errors"])

    def test_validate_plan_invalid_json(self, mock_session_storage, reset_global_session):
        """Test handling of malformed JSON."""
        from framework.mcp.agent_builder_server import validate_plan

        result = json.loads(validate_plan(plan_json="{invalid"))

        assert result["valid"] is False
        assert any("Invalid JSON" in e for e in result["errors"])

    def test_validate_plan_circular_dependency(self, mock_session_storage, reset_global_session):
        """Test detection of circular dependencies."""
        from framework.mcp.agent_builder_server import validate_plan

        plan = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "steps": [
                    {
                        "id": "step_a",
                        "description": "A",
                        "action": {"action_type": "llm_call"},
                        "dependencies": ["step_b"],
                    },
                    {
                        "id": "step_b",
                        "description": "B",
                        "action": {"action_type": "llm_call"},
                        "dependencies": ["step_a"],
                    },
                ],
            }
        )

        result = json.loads(validate_plan(plan_json=plan))

        assert result["valid"] is False
        assert any("Circular dependency" in e for e in result["errors"])

    def test_validate_plan_unknown_dependency(self, mock_session_storage, reset_global_session):
        """Test detection of unknown dependencies."""
        from framework.mcp.agent_builder_server import validate_plan

        plan = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "steps": [
                    {
                        "id": "step_1",
                        "description": "Step with missing dep",
                        "action": {"action_type": "llm_call"},
                        "dependencies": ["nonexistent_step"],
                    }
                ],
            }
        )

        result = json.loads(validate_plan(plan_json=plan))

        assert result["valid"] is False
        assert any("unknown dependency" in e for e in result["errors"])

    def test_validate_plan_invalid_action_type(self, mock_session_storage, reset_global_session):
        """Test rejection of invalid action types."""
        from framework.mcp.agent_builder_server import validate_plan

        plan = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "steps": [
                    {
                        "id": "step_1",
                        "description": "Invalid action",
                        "action": {"action_type": "invalid_type"},
                    }
                ],
            }
        )

        result = json.loads(validate_plan(plan_json=plan))

        assert result["valid"] is False
        assert any("invalid action_type" in e for e in result["errors"])

    def test_validate_plan_tool_use_requires_tool_name(
        self, mock_session_storage, reset_global_session
    ):
        """Test that tool_use action requires tool_name."""
        from framework.mcp.agent_builder_server import validate_plan

        plan = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "steps": [
                    {
                        "id": "step_1",
                        "description": "Tool without name",
                        "action": {"action_type": "tool_use"},  # Missing tool_name
                    }
                ],
            }
        )

        result = json.loads(validate_plan(plan_json=plan))

        assert result["valid"] is False
        assert any("tool_use requires tool_name" in e for e in result["errors"])


class TestPlanSimulation:
    """Tests for simulate_plan_execution."""

    def test_simulate_valid_plan(self, mock_session_storage, reset_global_session):
        """Test simulating a valid plan execution."""
        from framework.mcp.agent_builder_server import simulate_plan_execution

        plan = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "steps": [
                    {
                        "id": "step_1",
                        "description": "First step",
                        "action": {"action_type": "llm_call", "prompt": "Test"},
                        "dependencies": [],
                    },
                    {
                        "id": "step_2",
                        "description": "Second step",
                        "action": {"action_type": "llm_call", "prompt": "Test"},
                        "dependencies": ["step_1"],
                    },
                ],
            }
        )

        result = json.loads(simulate_plan_execution(plan_json=plan))

        assert result["success"] is True
        assert result["steps_simulated"] == 2
        assert result["plan_complete"] is True
        # First step should execute before second
        step_order = [s["step_id"] for s in result["execution_order"]]
        assert step_order.index("step_1") < step_order.index("step_2")

    def test_simulate_invalid_plan(self, mock_session_storage, reset_global_session):
        """Test that simulation fails for invalid plans."""
        from framework.mcp.agent_builder_server import simulate_plan_execution

        result = json.loads(simulate_plan_execution(plan_json="{invalid"))

        assert result["success"] is False

    def test_simulate_shows_parallel_candidates(self, mock_session_storage, reset_global_session):
        """Test that simulation identifies parallel execution candidates."""
        from framework.mcp.agent_builder_server import simulate_plan_execution

        plan = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "steps": [
                    {
                        "id": "step_a",
                        "description": "Independent A",
                        "action": {"action_type": "llm_call", "prompt": "A"},
                        "dependencies": [],
                    },
                    {
                        "id": "step_b",
                        "description": "Independent B",
                        "action": {"action_type": "llm_call", "prompt": "B"},
                        "dependencies": [],
                    },
                ],
            }
        )

        result = json.loads(simulate_plan_execution(plan_json=plan))

        assert result["success"] is True
        # First execution should show the other as parallel candidate
        first_exec = result["execution_order"][0]
        assert len(first_exec["parallel_candidates"]) == 1


# =============================================================================
# EVALUATION RULES TESTS
# =============================================================================


class TestEvaluationRules:
    """Tests for evaluation rule management."""

    @pytest.fixture(autouse=True)
    def reset_evaluation_rules(self):
        """Reset evaluation rules before each test."""
        import importlib

        server = importlib.import_module("framework.mcp.agent_builder_server")
        server._evaluation_rules = []
        yield
        server._evaluation_rules = []

    def test_add_evaluation_rule_valid(self, mock_session_storage, reset_global_session):
        """Test adding a valid evaluation rule."""
        from framework.mcp.agent_builder_server import add_evaluation_rule

        result = json.loads(
            add_evaluation_rule(
                rule_id="rule_1",
                description="Check for success flag",
                condition='result.get("success") == True',
                action="accept",
            )
        )

        assert result["success"] is True
        assert result["rule"]["id"] == "rule_1"
        assert result["total_rules"] == 1

    def test_add_evaluation_rule_invalid_action(self, mock_session_storage, reset_global_session):
        """Test rejection of invalid action type."""
        from framework.mcp.agent_builder_server import add_evaluation_rule

        result = json.loads(
            add_evaluation_rule(
                rule_id="rule_1",
                description="Test",
                condition="True",
                action="invalid_action",
            )
        )

        assert result["success"] is False
        assert "Invalid action" in result["error"]

    def test_add_evaluation_rule_duplicate(self, mock_session_storage, reset_global_session):
        """Test rejection of duplicate rule IDs."""
        from framework.mcp.agent_builder_server import add_evaluation_rule

        add_evaluation_rule(
            rule_id="rule_1",
            description="First rule",
            condition="True",
            action="accept",
        )

        result = json.loads(
            add_evaluation_rule(
                rule_id="rule_1",
                description="Duplicate",
                condition="False",
                action="retry",
            )
        )

        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_list_evaluation_rules_empty(self, mock_session_storage, reset_global_session):
        """Test listing rules when none exist."""
        from framework.mcp.agent_builder_server import list_evaluation_rules

        result = json.loads(list_evaluation_rules())

        assert result["rules"] == []
        assert result["total"] == 0

    def test_list_evaluation_rules_with_data(self, mock_session_storage, reset_global_session):
        """Test listing rules after adding some."""
        from framework.mcp.agent_builder_server import (
            add_evaluation_rule,
            list_evaluation_rules,
        )

        add_evaluation_rule(
            rule_id="rule_1", description="Rule 1", condition="True", action="accept"
        )
        add_evaluation_rule(
            rule_id="rule_2", description="Rule 2", condition="False", action="retry"
        )

        result = json.loads(list_evaluation_rules())

        assert result["total"] == 2
        assert len(result["rules"]) == 2

    def test_evaluation_rules_sorted_by_priority(self, mock_session_storage, reset_global_session):
        """Test that rules are sorted by priority (highest first)."""
        from framework.mcp.agent_builder_server import (
            add_evaluation_rule,
            list_evaluation_rules,
        )

        add_evaluation_rule(
            rule_id="low_priority",
            description="Low",
            condition="True",
            action="accept",
            priority=1,
        )
        add_evaluation_rule(
            rule_id="high_priority",
            description="High",
            condition="True",
            action="accept",
            priority=10,
        )

        result = json.loads(list_evaluation_rules())

        assert result["rules"][0]["id"] == "high_priority"
        assert result["rules"][1]["id"] == "low_priority"

    def test_remove_evaluation_rule(self, mock_session_storage, reset_global_session):
        """Test removing an evaluation rule."""
        from framework.mcp.agent_builder_server import (
            add_evaluation_rule,
            list_evaluation_rules,
            remove_evaluation_rule,
        )

        add_evaluation_rule(
            rule_id="to_remove", description="Test", condition="True", action="accept"
        )

        remove_result = json.loads(remove_evaluation_rule(rule_id="to_remove"))
        assert remove_result["success"] is True

        list_result = json.loads(list_evaluation_rules())
        assert list_result["total"] == 0

    def test_remove_evaluation_rule_not_found(self, mock_session_storage, reset_global_session):
        """Test removing a non-existent rule."""
        from framework.mcp.agent_builder_server import remove_evaluation_rule

        result = json.loads(remove_evaluation_rule(rule_id="nonexistent"))

        assert result["success"] is False
        assert "not found" in result["error"]


# =============================================================================
# EXPORT GRAPH TESTS
# =============================================================================


class TestExportGraph:
    """Tests for graph export functionality."""

    def _setup_exportable_graph(self):
        """Helper to create a complete, exportable graph."""
        from framework.mcp.agent_builder_server import (
            add_edge,
            add_node,
            create_session,
            set_goal,
        )

        create_session(name="Export Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test Goal",
            description="Test goal for export",
            success_criteria='[{"id": "sc1", "description": "Works correctly"}]',
        )
        add_node(
            node_id="start",
            name="Start Node",
            description="Entry point",
            node_type="llm_generate",
            input_keys='["input"]',
            output_keys='["result"]',
            system_prompt="Process input",
        )
        add_node(
            node_id="end",
            name="End Node",
            description="Exit point",
            node_type="llm_generate",
            input_keys='["result"]',
            output_keys='["output"]',
            system_prompt="Format output",
        )
        add_edge(edge_id="e1", source="start", target="end")

    def test_export_graph_no_goal(self, mock_session_storage, reset_global_session):
        """Test export fails when no goal is defined."""
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            export_graph,
        )

        create_session(name="Test Agent")
        add_node(
            node_id="node_1",
            name="Node",
            description="Test",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        result = json.loads(export_graph())

        assert result["success"] is False
        # Response uses "errors" list from validation
        assert any("goal" in str(e).lower() for e in result.get("errors", []))

    def test_export_graph_invalid_graph(self, mock_session_storage, reset_global_session):
        """Test export fails when graph is invalid."""
        from framework.mcp.agent_builder_server import create_session, export_graph, set_goal

        create_session(name="Test Agent")
        set_goal(
            goal_id="goal_1",
            name="Test",
            description="Test",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )
        # No nodes - invalid graph

        result = json.loads(export_graph())

        assert result["success"] is False

    def test_export_graph_creates_files(self, mock_session_storage, reset_global_session, tmp_path):
        """Test that export creates necessary files."""
        import os

        from framework.mcp.agent_builder_server import export_graph

        self._setup_exportable_graph()

        # Create exports directory in temp path
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()

        # Change to temp path so exports go there
        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = json.loads(export_graph())

            # Check that export succeeded
            assert result.get("success") is True or result.get("export_path") is not None
        finally:
            os.chdir(original_cwd)

    def test_get_session_status(self, mock_session_storage, reset_global_session):
        """Test getting session status."""
        from framework.mcp.agent_builder_server import (
            add_node,
            create_session,
            get_session_status,
            set_goal,
        )

        create_session(name="Status Test")
        set_goal(
            goal_id="goal_1",
            name="Test",
            description="Test",
            success_criteria='[{"id": "sc1", "description": "Test"}]',
        )
        add_node(
            node_id="node_1",
            name="Node",
            description="Test",
            node_type="llm_generate",
            input_keys="[]",
            output_keys="[]",
        )

        result = json.loads(get_session_status())

        assert result["session_id"].startswith("build_")
        assert result["name"] == "Status Test"
        # API uses "has_goal", not "goal_defined"
        assert result["has_goal"] is True
        assert result["node_count"] == 1
