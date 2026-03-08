"""Structural tests for SocialStake Agent."""


class TestAgentStructure:
    """Test agent graph structure."""

    def test_goal_defined(self, agent_module):
        """Goal is properly defined."""
        assert hasattr(agent_module, "goal")
        assert agent_module.goal.id == "social-stake-goal"
        assert len(agent_module.goal.success_criteria) == 5
        assert len(agent_module.goal.constraints) == 5

    def test_success_criteria_weights_sum_to_one(self, agent_module):
        """Success criteria weights should sum to approximately 1.0."""
        total = sum(sc.weight for sc in agent_module.goal.success_criteria)
        assert abs(total - 1.0) < 0.01

    def test_nodes_defined(self, agent_module):
        """All nodes are defined."""
        assert hasattr(agent_module, "nodes")
        node_ids = {n.id for n in agent_module.nodes}
        expected_nodes = {
            "intake",
            "stake-setup",
            "daily-checkin",
            "verify-proof",
            "update-progress",
            "settle-stake",
            "notify",
        }
        assert node_ids == expected_nodes

    def test_edges_defined(self, agent_module):
        """Edges connect nodes correctly."""
        assert hasattr(agent_module, "edges")
        assert len(agent_module.edges) == 11

    def test_entry_points(self, agent_module):
        """Entry points configured."""
        assert hasattr(agent_module, "entry_points")
        assert "start" in agent_module.entry_points
        assert agent_module.entry_points["start"] == "intake"

    def test_async_entry_points(self, agent_module):
        """Async entry points configured for timer."""
        assert hasattr(agent_module, "async_entry_points")
        assert len(agent_module.async_entry_points) == 1
        timer_ep = agent_module.async_entry_points[0]
        assert timer_ep.id == "daily-timer"
        assert timer_ep.trigger_type == "timer"
        assert timer_ep.entry_node == "daily-checkin"

    def test_forever_alive(self, agent_module):
        """Agent is forever-alive (no terminal nodes)."""
        assert hasattr(agent_module, "terminal_nodes")
        assert agent_module.terminal_nodes == []

    def test_conversation_mode(self, agent_module):
        """Continuous conversation mode enabled."""
        assert hasattr(agent_module, "conversation_mode")
        assert agent_module.conversation_mode == "continuous"

    def test_client_facing_nodes(self, agent_module):
        """Correct nodes are client-facing."""
        client_facing = [n for n in agent_module.nodes if n.client_facing]
        client_facing_ids = {n.id for n in client_facing}
        expected_client_facing = {
            "intake",
            "daily-checkin",
            "settle-stake",
            "notify",
        }
        assert client_facing_ids == expected_client_facing

    def test_intake_node_outputs(self, agent_module):
        """Intake node has correct output keys."""
        intake_node = next(n for n in agent_module.nodes if n.id == "intake")
        assert "user_goal" in intake_node.output_keys
        assert "stake_amount" in intake_node.output_keys
        assert "commitment_period" in intake_node.output_keys
        assert "verification_method" in intake_node.output_keys

    def test_stake_setup_node_outputs(self, agent_module):
        """Stake-setup node has correct output keys."""
        stake_node = next(n for n in agent_module.nodes if n.id == "stake-setup")
        assert "stake_id" in stake_node.output_keys
        assert "stake_status" in stake_node.output_keys
        assert "deadline" in stake_node.output_keys

    def test_daily_checkin_node_outputs(self, agent_module):
        """Daily-checkin node has correct output keys."""
        checkin_node = next(n for n in agent_module.nodes if n.id == "daily-checkin")
        assert "checkin_response" in checkin_node.output_keys
        assert "progress_update" in checkin_node.output_keys
        assert "proof_submitted" in checkin_node.output_keys

    def test_verify_proof_node_outputs(self, agent_module):
        """Verify-proof node has correct output keys."""
        verify_node = next(n for n in agent_module.nodes if n.id == "verify-proof")
        assert "verification_result" in verify_node.output_keys
        assert "confidence_score" in verify_node.output_keys
        assert "verification_notes" in verify_node.output_keys

    def test_update_progress_node_outputs(self, agent_module):
        """Update-progress node has correct output keys."""
        progress_node = next(n for n in agent_module.nodes if n.id == "update-progress")
        assert "progress_percentage" in progress_node.output_keys
        assert "stake_health" in progress_node.output_keys

    def test_settle_stake_node_outputs(self, agent_module):
        """Settle-stake node has correct output keys."""
        settle_node = next(n for n in agent_module.nodes if n.id == "settle-stake")
        assert "settlement_status" in settle_node.output_keys
        assert "amount_released" in settle_node.output_keys
        assert "settlement_tx" in settle_node.output_keys

    def test_notify_node_has_tools(self, agent_module):
        """Notify node has save_data and serve_file_to_user tools."""
        notify_node = next(n for n in agent_module.nodes if n.id == "notify")
        assert "save_data" in notify_node.tools
        assert "serve_file_to_user" in notify_node.tools


class TestEdgeConditions:
    """Test edge conditions for workflow routing."""

    def test_daily_checkin_to_verify_condition(self, agent_module):
        """Daily-checkin to verify-proof edge has correct condition."""
        edge = next(
            e
            for e in agent_module.edges
            if e.source == "daily-checkin" and e.target == "verify-proof"
        )
        assert edge.condition_expr == "proof_submitted == True"

    def test_daily_checkin_loop_condition(self, agent_module):
        """Daily-checkin loop edge has correct condition."""
        edge = next(
            e
            for e in agent_module.edges
            if e.source == "daily-checkin" and e.target == "daily-checkin"
        )
        assert "proof_submitted == False" in edge.condition_expr

    def test_notify_to_settle_condition(self, agent_module):
        """Notify to settle-stake edge has correct condition."""
        edge = next(
            e
            for e in agent_module.edges
            if e.source == "notify" and e.target == "settle-stake"
        )
        assert "days_remaining <= 0" in edge.condition_expr


class TestRunnerLoad:
    """Test AgentRunner can load the agent."""

    def test_runner_load_succeeds(self, runner_loaded):
        """AgentRunner.load() succeeds."""
        assert runner_loaded is not None

    def test_runner_has_goal(self, runner_loaded):
        """Runner has goal after load."""
        assert runner_loaded.goal is not None
        assert runner_loaded.goal.id == "social-stake-goal"

    def test_runner_has_nodes(self, runner_loaded):
        """Runner has nodes after load."""
        assert runner_loaded.graph is not None
        assert len(runner_loaded.graph.nodes) == 7


class TestAgentClass:
    """Test SocialStakeAgent class."""

    def test_default_agent_created(self, agent_module):
        """Default agent instance is created."""
        assert hasattr(agent_module, "default_agent")
        assert agent_module.default_agent is not None

    def test_validate_passes(self, agent_module):
        """Agent validation passes."""
        result = agent_module.default_agent.validate()
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_agent_info(self, agent_module):
        """Agent info returns correct data."""
        info = agent_module.default_agent.info()
        assert info["name"] == "SocialStake"
        assert "intake" in info["nodes"]
        assert "stake-setup" in info["nodes"]
        assert "daily-checkin" in info["nodes"]
        assert "verify-proof" in info["nodes"]
        assert "settle-stake" in info["nodes"]


class TestGoalConstraints:
    """Test goal constraints are properly defined."""

    def test_fund_safety_constraint(self, agent_module):
        """Fund safety constraint is defined."""
        constraint = next(
            (c for c in agent_module.goal.constraints if c.id == "c-fund-safety"), None
        )
        assert constraint is not None
        assert constraint.constraint_type == "hard"
        assert constraint.category == "security"

    def test_verification_integrity_constraint(self, agent_module):
        """Verification integrity constraint is defined."""
        constraint = next(
            (
                c
                for c in agent_module.goal.constraints
                if c.id == "c-verification-integrity"
            ),
            None,
        )
        assert constraint is not None
        assert constraint.constraint_type == "hard"

    def test_user_privacy_constraint(self, agent_module):
        """User privacy constraint is defined."""
        constraint = next(
            (c for c in agent_module.goal.constraints if c.id == "c-user-privacy"), None
        )
        assert constraint is not None
        assert constraint.category == "privacy"

    def test_minimum_stake_constraint(self, agent_module):
        """Minimum stake constraint is defined."""
        constraint = next(
            (c for c in agent_module.goal.constraints if c.id == "c-minimum-stake"),
            None,
        )
        assert constraint is not None
        assert constraint.constraint_type == "hard"
        assert constraint.category == "financial"
