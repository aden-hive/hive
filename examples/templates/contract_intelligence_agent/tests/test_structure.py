"""Structural tests for Contract Intelligence & Risk Agent."""


class TestAgentStructure:
    """Test agent graph structure."""

    def test_goal_defined(self, agent_module):
        """Goal is properly defined."""
        assert hasattr(agent_module, "goal")
        assert agent_module.goal.id == "contract-intelligence-risk"
        assert len(agent_module.goal.success_criteria) == 4

    def test_nodes_defined(self, agent_module):
        """All nodes are defined."""
        assert hasattr(agent_module, "nodes")
        node_ids = {n.id for n in agent_module.nodes}
        expected_nodes = {
            "intake",
            "extraction",
            "scoring",
            "flag",
            "hitl-review",
            "brief",
            "storage",
        }
        assert node_ids == expected_nodes

    def test_edges_defined(self, agent_module):
        """Edges connect nodes correctly."""
        assert hasattr(agent_module, "edges")
        edge_sources = {e.source for e in agent_module.edges}
        edge_targets = {e.target for e in agent_module.edges}
        assert edge_sources == {
            "intake",
            "extraction",
            "scoring",
            "flag",
            "hitl-review",
            "brief",
        }
        assert edge_targets == {
            "extraction",
            "scoring",
            "flag",
            "hitl-review",
            "brief",
            "storage",
            "intake",
        }

    def test_entry_points(self, agent_module):
        """Entry points configured."""
        assert hasattr(agent_module, "entry_points")
        assert "start" in agent_module.entry_points
        assert agent_module.entry_points["start"] == "intake"

    def test_terminal_nodes(self, agent_module):
        """Terminal node is storage."""
        assert hasattr(agent_module, "terminal_nodes")
        assert agent_module.terminal_nodes == ["storage"]

    def test_conversation_mode(self, agent_module):
        """Continuous conversation mode enabled."""
        assert hasattr(agent_module, "conversation_mode")
        assert agent_module.conversation_mode == "continuous"

    def test_client_facing_nodes(self, agent_module):
        """Correct nodes are client-facing."""
        client_facing = [n for n in agent_module.nodes if n.client_facing]
        client_facing_ids = {n.id for n in client_facing}
        expected_client_facing = {"intake", "hitl-review", "storage"}
        assert client_facing_ids == expected_client_facing

    def test_intake_node_has_pdf_tool(self, agent_module):
        """Intake node has PDF read tool."""
        intake_node = next(n for n in agent_module.nodes if n.id == "intake")
        assert "pdf_read" in intake_node.tools

    def test_hitl_review_node_is_client_facing(self, agent_module):
        """HITL review node is client-facing."""
        hitl_node = next(n for n in agent_module.nodes if n.id == "hitl-review")
        assert hitl_node.client_facing is True

    def test_hitl_review_node_has_approval_output(self, agent_module):
        """HITL review node has approval_decision output key."""
        hitl_node = next(n for n in agent_module.nodes if n.id == "hitl-review")
        assert "approval_decision" in hitl_node.output_keys

    def test_extraction_node_outputs_clauses(self, agent_module):
        """Extraction node outputs extracted_clauses."""
        extraction_node = next(n for n in agent_module.nodes if n.id == "extraction")
        assert "extracted_clauses" in extraction_node.output_keys

    def test_scoring_node_outputs_risk_scores(self, agent_module):
        """Scoring node outputs risk_scores."""
        scoring_node = next(n for n in agent_module.nodes if n.id == "scoring")
        assert "risk_scores" in scoring_node.output_keys
        assert "baseline_template" in scoring_node.output_keys

    def test_flag_node_outputs_anomalies(self, agent_module):
        """Flag node outputs anomalies and missing_clauses."""
        flag_node = next(n for n in agent_module.nodes if n.id == "flag")
        assert "anomalies" in flag_node.output_keys
        assert "missing_clauses" in flag_node.output_keys

    def test_brief_node_outputs_negotiation_brief(self, agent_module):
        """Brief node outputs negotiation_brief."""
        brief_node = next(n for n in agent_module.nodes if n.id == "brief")
        assert "negotiation_brief" in brief_node.output_keys

    def test_storage_node_outputs_summary(self, agent_module):
        """Storage node outputs contract_summary."""
        storage_node = next(n for n in agent_module.nodes if n.id == "storage")
        assert "contract_summary" in storage_node.output_keys

    def test_conditional_edges_for_hitl(self, agent_module):
        """HITL node has conditional edges for approval decisions."""
        hitl_edges = [e for e in agent_module.edges if e.source == "hitl-review"]
        assert len(hitl_edges) >= 3
        edge_conditions = {e.condition_expr for e in hitl_edges if e.condition_expr}
        assert any("approved" in c for c in edge_conditions)
        assert any("rejected" in c or "restart" in c for c in edge_conditions)


class TestRunnerLoad:
    """Test AgentRunner can load the agent."""

    def test_runner_load_succeeds(self, runner_loaded):
        """AgentRunner.load() succeeds."""
        assert runner_loaded is not None

    def test_runner_has_goal(self, runner_loaded):
        """Runner has goal after load."""
        assert runner_loaded.goal is not None
        assert runner_loaded.goal.id == "contract-intelligence-risk"

    def test_runner_has_nodes(self, runner_loaded):
        """Runner has nodes after load."""
        assert runner_loaded.graph is not None
        assert len(runner_loaded.graph.nodes) == 7


class TestAgentValidation:
    """Test agent validate() method."""

    def test_validate_returns_valid(self, agent_module):
        """Agent validate() returns valid=True."""
        result = agent_module.default_agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_has_hitl_warning_check(self, agent_module):
        """Validate method checks for HITL gate."""
        result = agent_module.default_agent.validate()
        assert "hitl-review" in agent_module.default_agent.info()["hitl_gate"]


class TestConfig:
    """Test configuration."""

    def test_default_config_exists(self, agent_module):
        """Default config is defined."""
        assert hasattr(agent_module, "default_config")
        assert agent_module.default_config.model is not None

    def test_metadata_exists(self, agent_module):
        """Metadata is defined."""
        assert hasattr(agent_module, "metadata")
        assert agent_module.metadata.name == "Contract Intelligence & Risk Agent"

    def test_baseline_template_exists(self, agent_module):
        """Baseline template is defined."""
        assert hasattr(agent_module, "DEFAULT_BASELINE_TEMPLATE")
        template = agent_module.DEFAULT_BASELINE_TEMPLATE
        assert "payment_terms" in template
        assert "liability_cap" in template
        assert "indemnification" in template
        assert "ip_ownership" in template
        assert "termination" in template
        assert "auto_renewal" in template
        assert "confidentiality" in template
        assert "governing_law" in template
