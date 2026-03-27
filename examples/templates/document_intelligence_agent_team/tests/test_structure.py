"""Structural tests for Document Intelligence Agent Team.

Validates the A2A architecture: Queen Bee (coordinator) with 3 Worker Bee
sub-agents connected via delegate_to_sub_agent, NOT edges.
"""


class TestGoal:
    """Test goal definition."""

    def test_goal_defined(self, agent_module):
        """Goal is properly defined."""
        assert hasattr(agent_module, "goal")
        assert agent_module.goal.id == "document-intelligence-consensus"

    def test_goal_has_success_criteria(self, agent_module):
        """Goal has 4 success criteria."""
        assert len(agent_module.goal.success_criteria) == 4

    def test_goal_has_constraints(self, agent_module):
        """Goal has constraints."""
        assert len(agent_module.goal.constraints) == 3


class TestNodes:
    """Test node definitions."""

    def test_all_nodes_defined(self, agent_module):
        """All 5 nodes are defined."""
        assert hasattr(agent_module, "nodes")
        node_ids = {n.id for n in agent_module.nodes}
        assert node_ids == {"intake", "coordinator", "researcher", "analyst", "strategist"}

    def test_client_facing_nodes(self, agent_module):
        """Correct nodes are client-facing."""
        client_facing = {n.id for n in agent_module.nodes if n.client_facing}
        assert client_facing == {"intake", "coordinator"}

    def test_non_client_facing_sub_agents(self, agent_module):
        """Worker Bee sub-agents are NOT client-facing."""
        worker_bees = [
            n for n in agent_module.nodes if n.id in {"researcher", "analyst", "strategist"}
        ]
        for node in worker_bees:
            assert not node.client_facing, f"{node.id} should not be client-facing"


class TestA2ACoordination:
    """Test the A2A sub-agent coordination pattern."""

    def test_coordinator_has_sub_agents(self, agent_module):
        """Coordinator declares all 3 Worker Bees as sub_agents."""
        coordinator = next(n for n in agent_module.nodes if n.id == "coordinator")
        assert set(coordinator.sub_agents) == {"researcher", "analyst", "strategist"}

    def test_sub_agents_have_no_sub_agents(self, agent_module):
        """Worker Bees do NOT have their own sub_agents (no nested delegation)."""
        worker_ids = {"researcher", "analyst", "strategist"}
        for node in agent_module.nodes:
            if node.id in worker_ids:
                assert len(node.sub_agents) == 0, f"Worker Bee {node.id} should not have sub_agents"

    def test_sub_agents_not_connected_by_edges(self, agent_module):
        """Sub-agent nodes should NOT appear in any edge (they're called via delegate)."""
        edge_nodes = set()
        for edge in agent_module.edges:
            edge_nodes.add(edge.source)
            edge_nodes.add(edge.target)

        sub_agent_ids = {"researcher", "analyst", "strategist"}
        assert edge_nodes.isdisjoint(sub_agent_ids), (
            f"Sub-agents should not appear in edges, found: {edge_nodes & sub_agent_ids}"
        )

    def test_sub_agents_have_system_prompts(self, agent_module):
        """Each Worker Bee has its own specialized system prompt."""
        worker_ids = {"researcher", "analyst", "strategist"}
        for node in agent_module.nodes:
            if node.id in worker_ids:
                assert node.system_prompt is not None, f"{node.id} missing system_prompt"
                assert len(node.system_prompt) > 50, f"{node.id} system_prompt too short"


class TestEdges:
    """Test edge definitions."""

    def test_edges_defined(self, agent_module):
        """Only 2 edges exist (intake ↔ coordinator loop)."""
        assert hasattr(agent_module, "edges")
        assert len(agent_module.edges) == 2

    def test_edge_sources_and_targets(self, agent_module):
        """Edges connect intake and coordinator bidirectionally."""
        edge_pairs = {(e.source, e.target) for e in agent_module.edges}
        assert edge_pairs == {("intake", "coordinator"), ("coordinator", "intake")}

    def test_all_edges_on_success(self, agent_module):
        """All edges use on_success condition."""
        from framework.graph.edge import EdgeCondition

        for edge in agent_module.edges:
            assert edge.condition == EdgeCondition.ON_SUCCESS


class TestAgentStructure:
    """Test overall agent structure."""

    def test_forever_alive(self, agent):
        """Agent is forever-alive (no terminal nodes)."""
        graph = agent._build_graph()
        assert graph.terminal_nodes == []

    def test_entry_node(self, agent):
        """Entry node is intake."""
        graph = agent._build_graph()
        assert graph.entry_node == "intake"

    def test_graph_builds_successfully(self, agent):
        """Graph builds without errors."""
        graph = agent._build_graph()
        assert graph is not None
        assert len(graph.nodes) == 5
        assert len(graph.edges) == 2

    def test_validate_passes(self, agent):
        """Agent validation passes."""
        result = agent.validate()  # internally calls _build_graph()
        assert result["valid"], f"Validation failed: {result['errors']}"

    def test_info_returns_dict(self, agent):
        """Info method returns a dict with expected keys."""
        info = agent.info()
        assert isinstance(info, dict)
        assert "Document Intelligence" in info["name"]
        assert "Queen Bee" in info["pattern"]
        assert "Worker Bee" in info["pattern"]


class TestConfig:
    """Test configuration."""

    def test_default_config_exists(self, agent_module):
        """Default config is available."""
        assert hasattr(agent_module, "default_config")

    def test_metadata_exists(self, agent_module):
        """Agent metadata is available."""
        assert hasattr(agent_module, "metadata")
        assert "Document Intelligence" in agent_module.metadata.name

    def test_worker_models_exists(self, agent_module):
        """Worker models config is available."""
        assert hasattr(agent_module, "worker_models")
        assert agent_module.worker_models.researcher is None  # default
        assert agent_module.worker_models.analyst is None
        assert agent_module.worker_models.strategist is None
