"""
Tests for graph visualization export (Mermaid and DOT formats).

Tests the to_mermaid() and to_dot() methods added to GraphSpec.
"""

import pytest
from framework.graph.edge import GraphSpec, EdgeSpec, EdgeCondition, AsyncEntryPointSpec
from framework.graph.node import NodeSpec


class TestGraphVisualizationMermaid:
    """Tests for Mermaid diagram export."""

    def _create_simple_graph(self) -> GraphSpec:
        """Create a simple linear graph for testing."""
        return GraphSpec(
            id="simple-graph",
            goal_id="test-001",
            entry_node="node_a",
            terminal_nodes=["node_c"],
            nodes=[
                NodeSpec(id="node_a", name="Node A", description="First node", node_type="llm_generate"),
                NodeSpec(id="node_b", name="Node B", description="Second node", node_type="llm_tool_use"),
                NodeSpec(id="node_c", name="Node C", description="Third node", node_type="function"),
            ],
            edges=[
                EdgeSpec(id="e1", source="node_a", target="node_b", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e2", source="node_b", target="node_c", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

    def test_mermaid_basic_structure(self):
        """Test that Mermaid output has correct basic structure."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid()

        # Check header
        assert output.startswith("graph TD")

        # Check all nodes are present
        assert "node_a" in output
        assert "node_b" in output
        assert "node_c" in output

        # Check edges are present
        assert "node_a -->" in output
        assert "node_b -->" in output

    def test_mermaid_node_labels_with_type(self):
        """Test that node labels include node type when enabled."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid(include_node_type=True)

        assert "Node A<br/><i>llm_generate</i>" in output
        assert "Node B<br/><i>llm_tool_use</i>" in output
        assert "Node C<br/><i>function</i>" in output

    def test_mermaid_node_labels_without_type(self):
        """Test that node labels exclude node type when disabled."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid(include_node_type=False)

        assert 'node_a["Node A"]' in output
        assert "llm_generate" not in output

    def test_mermaid_edge_conditions(self):
        """Test that edge conditions are shown as labels."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid(include_conditions=True)

        assert "|always|" in output
        assert "|on_success|" in output

    def test_mermaid_edge_conditions_hidden(self):
        """Test that edge conditions are hidden when disabled."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid(include_conditions=False)

        assert "|always|" not in output
        assert "|on_success|" not in output
        # Should have plain arrows
        assert "node_a --> node_b" in output

    def test_mermaid_direction_options(self):
        """Test different direction options."""
        graph = self._create_simple_graph()

        assert graph.to_mermaid(direction="TD").startswith("graph TD")
        assert graph.to_mermaid(direction="LR").startswith("graph LR")
        assert graph.to_mermaid(direction="BT").startswith("graph BT")
        assert graph.to_mermaid(direction="RL").startswith("graph RL")

    def test_mermaid_node_styling_entry(self):
        """Test that entry node gets green styling."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid()

        # Entry node should be green
        assert "style node_a fill:#90EE90,stroke:#228B22" in output

    def test_mermaid_node_styling_terminal(self):
        """Test that terminal node gets pink styling."""
        graph = self._create_simple_graph()
        output = graph.to_mermaid()

        # Terminal node should be pink
        assert "style node_c fill:#FFB6C1,stroke:#DC143C" in output

    def test_mermaid_node_styling_pause(self):
        """Test that pause/HITL node gets gold styling."""
        graph = GraphSpec(
            id="pause-graph",
            goal_id="test-002",
            entry_node="start",
            terminal_nodes=["end"],
            pause_nodes=["review"],
            nodes=[
                NodeSpec(id="start", name="Start", description="", node_type="llm_generate"),
                NodeSpec(id="review", name="Review", description="", node_type="human_input"),
                NodeSpec(id="end", name="End", description="", node_type="function"),
            ],
            edges=[
                EdgeSpec(id="e1", source="start", target="review", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e2", source="review", target="end", condition=EdgeCondition.ALWAYS),
            ],
        )
        output = graph.to_mermaid()

        # Pause node should be gold
        assert "style review fill:#FFD700,stroke:#FFA500" in output

    def test_mermaid_async_entry_points(self):
        """Test that async entry point nodes get blue styling."""
        graph = GraphSpec(
            id="async-graph",
            goal_id="test-003",
            entry_node="main",
            terminal_nodes=["end"],
            async_entry_points=[
                AsyncEntryPointSpec(
                    id="webhook",
                    name="Webhook Handler",
                    entry_node="webhook_entry",
                    trigger_type="webhook",
                ),
            ],
            nodes=[
                NodeSpec(id="main", name="Main", description="", node_type="llm_generate"),
                NodeSpec(id="webhook_entry", name="Webhook Entry", description="", node_type="function"),
                NodeSpec(id="end", name="End", description="", node_type="function"),
            ],
            edges=[
                EdgeSpec(id="e1", source="main", target="end", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e2", source="webhook_entry", target="end", condition=EdgeCondition.ALWAYS),
            ],
        )
        output = graph.to_mermaid()

        # Async entry point should be blue
        assert "style webhook_entry fill:#87CEEB,stroke:#4682B4" in output

    def test_mermaid_empty_graph(self):
        """Test Mermaid output for empty graph."""
        graph = GraphSpec(
            id="empty-graph",
            goal_id="test-004",
            entry_node="none",
            nodes=[],
            edges=[],
        )
        output = graph.to_mermaid()

        assert output.startswith("graph TD")
        # Should not crash, just have header

    def test_mermaid_special_characters_in_name(self):
        """Test that special characters in node names are escaped."""
        graph = GraphSpec(
            id="special-graph",
            goal_id="test-005",
            entry_node="node_1",
            terminal_nodes=["node_1"],
            nodes=[
                NodeSpec(
                    id="node_1",
                    name='Node with "quotes" and <tags>',
                    description="",
                    node_type="function"
                ),
            ],
            edges=[],
        )
        output = graph.to_mermaid()

        # Should escape quotes and angle brackets
        assert "&quot;" in output
        assert "&lt;" in output
        assert "&gt;" in output

    def test_mermaid_conditional_edge(self):
        """Test conditional edge with expression."""
        graph = GraphSpec(
            id="conditional-graph",
            goal_id="test-006",
            entry_node="check",
            terminal_nodes=["pass", "fail"],
            nodes=[
                NodeSpec(id="check", name="Check", description="", node_type="function"),
                NodeSpec(id="pass", name="Pass", description="", node_type="function"),
                NodeSpec(id="fail", name="Fail", description="", node_type="function"),
            ],
            edges=[
                EdgeSpec(
                    id="e1",
                    source="check",
                    target="pass",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="output.score > 0.8"
                ),
                EdgeSpec(
                    id="e2",
                    source="check",
                    target="fail",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="output.score <= 0.8"
                ),
            ],
        )
        output = graph.to_mermaid()

        # Note: > and < are escaped to &gt; and &lt; in Mermaid
        assert "if: output.score &gt; 0.8" in output
        assert "if: output.score &lt;= 0.8" in output

    def test_mermaid_llm_decide_edge(self):
        """Test LLM decide edge condition."""
        graph = GraphSpec(
            id="llm-decide-graph",
            goal_id="test-007",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[
                NodeSpec(id="start", name="Start", description="", node_type="function"),
                NodeSpec(id="end", name="End", description="", node_type="function"),
            ],
            edges=[
                EdgeSpec(
                    id="e1",
                    source="start",
                    target="end",
                    condition=EdgeCondition.LLM_DECIDE,
                ),
            ],
        )
        output = graph.to_mermaid()

        assert "|llm_decide|" in output

    def test_mermaid_long_condition_truncation(self):
        """Test that long condition expressions are truncated."""
        graph = GraphSpec(
            id="truncate-graph",
            goal_id="test-008",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[
                NodeSpec(id="start", name="Start", description="", node_type="function"),
                NodeSpec(id="end", name="End", description="", node_type="function"),
            ],
            edges=[
                EdgeSpec(
                    id="e1",
                    source="start",
                    target="end",
                    condition=EdgeCondition.CONDITIONAL,
                    condition_expr="output.very_long_variable_name > some_threshold_value_here"
                ),
            ],
        )
        output = graph.to_mermaid()

        # Should be truncated with ...
        assert "..." in output
        # Should not contain the full expression
        assert "some_threshold_value_here" not in output


class TestGraphVisualizationDot:
    """Tests for DOT/Graphviz export."""

    def _create_simple_graph(self) -> GraphSpec:
        """Create a simple linear graph for testing."""
        return GraphSpec(
            id="simple-graph",
            goal_id="test-001",
            entry_node="node_a",
            terminal_nodes=["node_c"],
            nodes=[
                NodeSpec(id="node_a", name="Node A", description="First node", node_type="llm_generate"),
                NodeSpec(id="node_b", name="Node B", description="Second node", node_type="llm_tool_use"),
                NodeSpec(id="node_c", name="Node C", description="Third node", node_type="function"),
            ],
            edges=[
                EdgeSpec(id="e1", source="node_a", target="node_b", condition=EdgeCondition.ALWAYS),
                EdgeSpec(id="e2", source="node_b", target="node_c", condition=EdgeCondition.ON_SUCCESS),
            ],
        )

    def test_dot_basic_structure(self):
        """Test that DOT output has correct basic structure."""
        graph = self._create_simple_graph()
        output = graph.to_dot()

        # Check header
        assert 'digraph "simple-graph"' in output
        assert "rankdir=TD" in output

        # Check closing brace
        assert output.strip().endswith("}")

    def test_dot_node_definitions(self):
        """Test that nodes are properly defined."""
        graph = self._create_simple_graph()
        output = graph.to_dot()

        assert "node_a [label=" in output
        assert "node_b [label=" in output
        assert "node_c [label=" in output

    def test_dot_node_labels_with_type(self):
        """Test that node labels include node type."""
        graph = self._create_simple_graph()
        output = graph.to_dot(include_node_type=True)

        assert "Node A\\n(llm_generate)" in output
        assert "Node B\\n(llm_tool_use)" in output

    def test_dot_node_labels_without_type(self):
        """Test that node labels exclude node type when disabled."""
        graph = self._create_simple_graph()
        output = graph.to_dot(include_node_type=False)

        assert 'label="Node A"' in output
        assert "llm_generate" not in output

    def test_dot_edge_definitions(self):
        """Test that edges are properly defined."""
        graph = self._create_simple_graph()
        output = graph.to_dot()

        assert "node_a -> node_b" in output
        assert "node_b -> node_c" in output

    def test_dot_edge_labels(self):
        """Test that edge labels are included."""
        graph = self._create_simple_graph()
        output = graph.to_dot(include_conditions=True)

        assert 'label="always"' in output
        assert 'label="on_success"' in output

    def test_dot_edge_labels_hidden(self):
        """Test that edge labels are hidden when disabled."""
        graph = self._create_simple_graph()
        output = graph.to_dot(include_conditions=False)

        assert 'label="always"' not in output
        # Should have edges without labels
        assert "node_a -> node_b;" in output

    def test_dot_node_colors_entry(self):
        """Test that entry node gets green fill color."""
        graph = self._create_simple_graph()
        output = graph.to_dot()

        # Entry node should have green fill
        assert 'fillcolor="#90EE90"' in output

    def test_dot_node_colors_terminal(self):
        """Test that terminal node gets pink fill color."""
        graph = self._create_simple_graph()
        output = graph.to_dot()

        # Terminal node should have pink fill
        assert 'fillcolor="#FFB6C1"' in output

    def test_dot_empty_graph(self):
        """Test DOT output for empty graph."""
        graph = GraphSpec(
            id="empty-graph",
            goal_id="test-004",
            entry_node="none",
            nodes=[],
            edges=[],
        )
        output = graph.to_dot()

        assert 'digraph "empty-graph"' in output
        assert output.strip().endswith("}")

    def test_dot_special_characters_in_name(self):
        """Test that special characters in node names are escaped."""
        graph = GraphSpec(
            id="special-graph",
            goal_id="test-005",
            entry_node="node_1",
            terminal_nodes=["node_1"],
            nodes=[
                NodeSpec(
                    id="node_1",
                    name='Node with "quotes"',
                    description="",
                    node_type="function"
                ),
            ],
            edges=[],
        )
        output = graph.to_dot()

        # Should escape quotes
        assert '\\"' in output

    def test_dot_special_characters_in_id(self):
        """Test that special characters in node IDs are sanitized."""
        graph = GraphSpec(
            id="special-id-graph",
            goal_id="test-006",
            entry_node="node-with-dashes",
            terminal_nodes=["node-with-dashes"],
            nodes=[
                NodeSpec(
                    id="node-with-dashes",
                    name="Node",
                    description="",
                    node_type="function"
                ),
            ],
            edges=[],
        )
        output = graph.to_dot()

        # Dashes should be replaced with underscores
        assert "node_with_dashes" in output
        assert "node-with-dashes" not in output


class TestSanitizeAndEscape:
    """Tests for ID sanitization and label escaping helper methods."""

    def test_sanitize_id_with_dashes(self):
        """Test that dashes are replaced with underscores."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        assert graph._sanitize_id("node-id-here") == "node_id_here"

    def test_sanitize_id_with_spaces(self):
        """Test that spaces are replaced with underscores."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        assert graph._sanitize_id("node id here") == "node_id_here"

    def test_sanitize_id_starting_with_number(self):
        """Test that IDs starting with numbers get prefixed."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        result = graph._sanitize_id("123node")
        assert result.startswith("n_")

    def test_escape_label_mermaid_quotes(self):
        """Test that quotes are escaped for Mermaid."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        result = graph._escape_label('Say "hello"', "mermaid")
        assert "&quot;" in result

    def test_escape_label_dot_quotes(self):
        """Test that quotes are escaped for DOT."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        result = graph._escape_label('Say "hello"', "dot")
        assert '\\"' in result

    def test_escape_label_mermaid_newlines(self):
        """Test that newlines are converted to <br/> for Mermaid."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        result = graph._escape_label("Line 1\nLine 2", "mermaid")
        # Newlines should be converted to <br/> (not escaped)
        assert result == "Line 1<br/>Line 2"

    def test_escape_label_dot_newlines(self):
        """Test that newlines are escaped for DOT."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        result = graph._escape_label("Line 1\nLine 2", "dot")
        assert "\\n" in result


class TestEdgeLabels:
    """Tests for edge label generation."""

    def test_get_edge_label_always(self):
        """Test label for ALWAYS condition."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        edge = EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ALWAYS)
        assert graph._get_edge_label(edge) == "always"

    def test_get_edge_label_on_success(self):
        """Test label for ON_SUCCESS condition."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        edge = EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_SUCCESS)
        assert graph._get_edge_label(edge) == "on_success"

    def test_get_edge_label_on_failure(self):
        """Test label for ON_FAILURE condition."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        edge = EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.ON_FAILURE)
        assert graph._get_edge_label(edge) == "on_failure"

    def test_get_edge_label_llm_decide(self):
        """Test label for LLM_DECIDE condition."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        edge = EdgeSpec(id="e1", source="a", target="b", condition=EdgeCondition.LLM_DECIDE)
        assert graph._get_edge_label(edge) == "llm_decide"

    def test_get_edge_label_conditional(self):
        """Test label for CONDITIONAL condition."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        edge = EdgeSpec(
            id="e1", source="a", target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="x > 5"
        )
        assert graph._get_edge_label(edge) == "if: x > 5"

    def test_get_edge_label_conditional_truncation(self):
        """Test that long conditional expressions are truncated."""
        graph = GraphSpec(id="test", goal_id="test", entry_node="test", nodes=[], edges=[])
        edge = EdgeSpec(
            id="e1", source="a", target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="this_is_a_very_long_expression_that_exceeds_the_limit"
        )
        label = graph._get_edge_label(edge, truncate=30)
        assert len(label) <= 34  # "if: " + 30 chars
        assert "..." in label
