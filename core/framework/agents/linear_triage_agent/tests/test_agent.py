"""Tests for Linear Triage & Auto-Labeling Agent."""



class TestAgentStructure:
    """Test agent structure and configuration."""

    def test_agent_module_loads(self, agent_module):
        """Verify the agent module loads successfully."""
        assert agent_module is not None

    def test_goal_defined(self, agent_module):
        """Verify goal is defined and has required attributes."""
        goal = agent_module.goal
        assert goal is not None
        assert goal.id == "linear-triage-goal"
        assert goal.name == "Linear Triage & Auto-Labeling"
        assert len(goal.success_criteria) >= 3
        assert len(goal.constraints) >= 1

    def test_nodes_defined(self, agent_module):
        """Verify all required nodes are defined."""
        nodes = agent_module.nodes
        node_ids = {n.id for n in nodes}

        expected_nodes = {"classify", "security", "bug", "feature", "action"}
        assert expected_nodes == node_ids

    def test_edges_defined(self, agent_module):
        """Verify edges include conditional routing."""
        edges = agent_module.edges
        edge_ids = {e.id for e in edges}

        expected_edges = {
            "classify-to-security",
            "classify-to-bug",
            "classify-to-feature",
            "security-to-action",
            "bug-to-action",
            "feature-to-action",
        }
        assert expected_edges == edge_ids

    def test_conditional_edges_use_condition_expr(self, agent_module):
        """Verify routing edges use CONDITIONAL with condition_expr."""
        from framework.graph.edge import EdgeCondition

        routing_edges = [
            e
            for e in agent_module.edges
            if e.source == "classify" and e.target in {"security", "bug", "feature"}
        ]

        assert len(routing_edges) == 3

        for edge in routing_edges:
            assert edge.condition == EdgeCondition.CONDITIONAL
            assert edge.condition_expr is not None
            assert "issue_type" in edge.condition_expr

    def test_entry_node_is_classify(self, agent_module):
        """Verify entry node is the classify node."""
        assert agent_module.entry_node == "classify"

    def test_entry_points_defined(self, agent_module):
        """Verify entry points are properly defined."""
        entry_points = agent_module.entry_points
        assert isinstance(entry_points, dict)
        assert "start" in entry_points
        assert entry_points["start"] == "classify"

    def test_terminal_nodes_defined(self, agent_module):
        """Verify terminal nodes include action node."""
        terminal_nodes = agent_module.terminal_nodes
        assert "action" in terminal_nodes

    def test_conversation_mode_continuous(self, agent_module):
        """Verify conversation mode is continuous."""
        assert agent_module.conversation_mode == "continuous"

    def test_loop_config_defined(self, agent_module):
        """Verify loop config has required keys."""
        loop_config = agent_module.loop_config
        assert "max_iterations" in loop_config
        assert "max_tool_calls_per_turn" in loop_config
        assert "max_history_tokens" in loop_config


class TestNodeConfiguration:
    """Test individual node configurations."""

    def test_classify_node_config(self, agent_module):
        """Verify classify node configuration."""
        classify = next(n for n in agent_module.nodes if n.id == "classify")

        assert classify.node_type == "event_loop"
        assert "raw_issue" in classify.input_keys
        assert "issue_type" in classify.output_keys
        assert "severity" in classify.output_keys
        assert "suggested_labels" in classify.output_keys
        assert classify.max_node_visits == 1

    def test_security_node_config(self, agent_module):
        """Verify security node configuration."""
        security = next(n for n in agent_module.nodes if n.id == "security")

        assert security.node_type == "event_loop"
        assert "raw_issue" in security.input_keys
        assert "node_context" in security.output_keys
        assert "escalation_required" in security.output_keys

    def test_bug_node_config(self, agent_module):
        """Verify bug node configuration."""
        bug = next(n for n in agent_module.nodes if n.id == "bug")

        assert bug.node_type == "event_loop"
        assert "raw_issue" in bug.input_keys
        assert "node_context" in bug.output_keys

    def test_feature_node_config(self, agent_module):
        """Verify feature node configuration."""
        feature = next(n for n in agent_module.nodes if n.id == "feature")

        assert feature.node_type == "event_loop"
        assert "raw_issue" in feature.input_keys
        assert "node_context" in feature.output_keys

    def test_action_node_config(self, agent_module):
        """Verify action node configuration."""
        action = next(n for n in agent_module.nodes if n.id == "action")

        assert action.node_type == "event_loop"
        assert "raw_issue" in action.input_keys
        assert "issue_type" in action.input_keys
        assert "node_context" in action.input_keys
        assert "final_payload_status" in action.output_keys
        assert "save_data" in action.tools


class TestAgentValidation:
    """Test agent validation."""

    def test_default_agent_validates(self, agent_module):
        """Verify default_agent passes validation."""
        result = agent_module.default_agent.validate()
        assert result["valid"], f"Validation errors: {result['errors']}"

    def test_agent_class_has_required_methods(self, agent_module):
        """Verify LinearTriageAgent has required methods."""
        agent = agent_module.LinearTriageAgent()

        assert hasattr(agent, "run")
        assert hasattr(agent, "start")
        assert hasattr(agent, "stop")
        assert hasattr(agent, "info")
        assert hasattr(agent, "validate")
        assert callable(agent.run)

    def test_agent_info_returns_expected_keys(self, agent_module):
        """Verify info() returns expected information."""
        info = agent_module.default_agent.info()

        expected_keys = {
            "name",
            "version",
            "description",
            "goal",
            "nodes",
            "edges",
            "entry_node",
            "entry_points",
            "terminal_nodes",
            "client_facing_nodes",
            "pattern",
        }
        assert expected_keys.issubset(info.keys())


class TestRouterPattern:
    """Test the Router Pattern implementation."""

    def test_all_branches_converge_at_action(self, agent_module):
        """Verify all specialized nodes converge at action node."""
        edges = agent_module.edges

        incoming_to_action = [e for e in edges if e.target == "action"]
        sources = {e.source for e in incoming_to_action}

        assert sources == {"security", "bug", "feature"}

    def test_conditional_routing_covers_all_types(self, agent_module):
        """Verify conditional routing covers all issue types."""
        from framework.graph.edge import EdgeCondition

        edges = agent_module.edges

        conditional_from_classify = [
            e for e in edges if e.source == "classify" and e.condition == EdgeCondition.CONDITIONAL
        ]

        types_covered = set()
        for edge in conditional_from_classify:
            if "security" in edge.condition_expr:
                types_covered.add("security")
            elif "bug" in edge.condition_expr:
                types_covered.add("bug")
            elif "feature" in edge.condition_expr:
                types_covered.add("feature")

        assert types_covered == {"security", "bug", "feature"}

    def test_priority_ordering(self, agent_module):
        """Verify edge priorities are set for proper routing evaluation."""
        edges = agent_module.edges

        classify_outgoing = [e for e in edges if e.source == "classify"]

        priorities = [e.priority for e in classify_outgoing]
        assert all(p > 0 for p in priorities), "All priorities should be positive"
