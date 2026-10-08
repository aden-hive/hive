"""Structural tests for Email Reply Agent."""


class TestAgentStructure:
    """Test agent graph structure."""

    def test_goal_defined(self, agent_module):
        """Goal is properly defined."""
        assert hasattr(agent_module, "goal")
        assert agent_module.goal.id == "email-reply-goal"
        assert len(agent_module.goal.success_criteria) == 3

    def test_nodes_defined(self, agent_module):
        """All nodes are defined."""
        assert hasattr(agent_module, "nodes")
        node_ids = {n.id for n in agent_module.nodes}
        assert node_ids == {"intake", "search", "confirm-draft"}

    def test_edges_defined(self, agent_module):
        """Edges connect nodes correctly."""
        assert hasattr(agent_module, "edges")
        edge_sources = {e.source for e in agent_module.edges}
        edge_targets = {e.target for e in agent_module.edges}
        assert edge_sources == {"intake", "search", "confirm-draft"}
        assert edge_targets == {"search", "confirm-draft", "intake"}
        # Check conditional edges for restart and batch_complete
        confirm_edges = [e for e in agent_module.edges if e.source == "confirm-draft"]
        assert len(confirm_edges) == 2
        edge_conditions = {e.condition_expr for e in confirm_edges}
        assert "restart == True" in edge_conditions
        assert (
            "batch_complete == True and send_started == True and send_count >= 1 and sent_message_ids is not None and len(sent_message_ids) >= 1"
            in edge_conditions
        )

    def test_entry_points(self, agent_module):
        """Entry points configured."""
        assert hasattr(agent_module, "entry_points")
        assert "start" in agent_module.entry_points
        assert agent_module.entry_points["start"] == "intake"

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
        assert client_facing_ids == {"intake", "confirm-draft"}

    def test_search_node_has_gmail_tools(self, agent_module):
        """Search node has Gmail listing tools."""
        search_node = next(n for n in agent_module.nodes if n.id == "search")
        assert "gmail_list_messages" in search_node.tools
        assert "gmail_get_message" in search_node.tools

    def test_confirm_draft_node_has_reply_tool(self, agent_module):
        """Confirm-draft node has reply tool."""
        draft_node = next(n for n in agent_module.nodes if n.id == "confirm-draft")
        assert "gmail_reply_email" in draft_node.tools

    def test_confirm_draft_node_has_restart_output(self, agent_module):
        """Confirm-draft node has restart output key for logic changes."""
        draft_node = next(n for n in agent_module.nodes if n.id == "confirm-draft")
        assert "restart" in draft_node.output_keys
        assert "batch_complete" in draft_node.output_keys


class TestRunnerLoad:
    """Test AgentRunner can load the agent."""

    def test_runner_load_succeeds(self, runner_loaded):
        """AgentLoader.load() succeeds."""
        assert runner_loaded is not None

    def test_runner_has_goal(self, runner_loaded):
        """Runner has goal after load."""
        assert runner_loaded.goal is not None
        assert runner_loaded.goal.id == "email-reply-goal"

    def test_runner_has_nodes(self, runner_loaded):
        """Runner has nodes after load."""
        assert runner_loaded.graph is not None
        assert len(runner_loaded.graph.nodes) == 3
