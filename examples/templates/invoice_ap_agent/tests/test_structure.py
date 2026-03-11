"""Structure validation tests for Invoice & AP Automation Agent."""



class TestInvoiceAPAgentStructure:
    """Test agent structure and configuration."""

    def test_agent_imports(self):
        """Test that agent can be imported."""
        from invoice_ap_agent import InvoiceAPAgent, default_agent, edges, goal, nodes

        assert InvoiceAPAgent is not None
        assert default_agent is not None
        assert goal is not None
        assert nodes is not None
        assert edges is not None

    def test_goal_definition(self):
        """Test goal has required fields."""
        from invoice_ap_agent import goal

        assert goal.id == "invoice-ap-automation"
        assert goal.name == "Invoice & AP Automation Agent"
        assert len(goal.success_criteria) == 4
        assert len(goal.constraints) == 3

    def test_success_criteria(self):
        """Test success criteria targets."""
        from invoice_ap_agent import goal

        criteria_map = {sc.id: sc for sc in goal.success_criteria}

        assert "extraction-accuracy" in criteria_map
        assert "92%" in criteria_map["extraction-accuracy"].target

        assert "discrepancy-detection" in criteria_map
        assert "95%" in criteria_map["discrepancy-detection"].target

        assert "human-confirmation" in criteria_map
        assert "100%" in criteria_map["human-confirmation"].target

        assert "processing-time" in criteria_map
        assert "<2" in criteria_map["processing-time"].target

    def test_node_count(self):
        """Test that all 7 nodes are defined."""
        from invoice_ap_agent import nodes

        assert len(nodes) == 7

    def test_node_ids(self):
        """Test that all required nodes exist."""
        from invoice_ap_agent import nodes

        node_ids = {n.id for n in nodes}

        expected_nodes = {
            "intake",
            "extraction",
            "validation",
            "hitl-review",
            "routing",
            "post",
            "digest",
        }

        assert expected_nodes == node_ids

    def test_hitl_node_exists(self):
        """Test that human-in-the-loop review node exists."""
        from invoice_ap_agent import nodes

        node_ids = {n.id for n in nodes}
        assert "hitl-review" in node_ids

    def test_hitl_node_is_client_facing(self):
        """Test that HITL node is client-facing."""
        from invoice_ap_agent import nodes

        hitl_node = next((n for n in nodes if n.id == "hitl-review"), None)
        assert hitl_node is not None
        assert hitl_node.client_facing is True

    def test_edge_count(self):
        """Test that edges connect all nodes."""
        from invoice_ap_agent import edges

        assert len(edges) == 8

    def test_pipeline_order(self):
        """Test that main pipeline edges exist."""
        from invoice_ap_agent import edges

        edge_ids = {e.id for e in edges}

        required_edges = {
            "intake-to-extraction",
            "extraction-to-validation",
            "validation-to-hitl",
            "hitl-to-routing-approved",
            "routing-to-post",
            "post-to-digest",
        }

        for edge in required_edges:
            assert edge in edge_ids, f"Missing edge: {edge}"

    def test_conditional_edges(self):
        """Test that conditional edges for approval decisions exist."""
        from framework.graph import EdgeCondition
        from invoice_ap_agent import edges

        conditional_edges = [
            e for e in edges if e.condition == EdgeCondition.CONDITIONAL
        ]
        assert len(conditional_edges) >= 3

        edge_sources = {e.source for e in conditional_edges}
        assert "hitl-review" in edge_sources

    def test_entry_point(self):
        """Test entry point configuration."""
        from invoice_ap_agent import entry_node, entry_points

        assert entry_node == "intake"
        assert entry_points == {"start": "intake"}

    def test_terminal_nodes(self):
        """Test terminal nodes configuration."""
        from invoice_ap_agent import terminal_nodes

        assert "digest" in terminal_nodes

    def test_validate_method(self):
        """Test agent validate method."""
        from invoice_ap_agent import default_agent

        result = default_agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_info_method(self):
        """Test agent info method."""
        from invoice_ap_agent import default_agent

        info = default_agent.info()

        assert info["name"] == "Invoice & AP Automation Agent"
        assert len(info["nodes"]) == 7
        assert info["hitl_gate"] == "hitl-review"

    def test_metadata(self):
        """Test agent metadata."""
        from invoice_ap_agent import metadata

        assert metadata.name == "Invoice & AP Automation Agent"
        assert metadata.version == "1.0.0"

    def test_config(self):
        """Test runtime config."""
        from invoice_ap_agent import default_config

        assert default_config.model is not None
        assert default_config.temperature == 0.3
