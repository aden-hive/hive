"""Integration tests for error handling in runner and orchestrator.

Run with:
    cd core
    pytest tests/test_error_handling_integration.py -v
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from framework.llm.provider import LLMProvider, LLMResponse
from framework.runner.orchestrator import AgentOrchestrator, RoutingDecision
from framework.runner.protocol import CapabilityLevel, CapabilityResponse


class TestOrchestratorErrorHandling:
    """Test orchestrator handles errors gracefully with proper logging."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM provider."""
        mock = Mock(spec=LLMProvider)
        return mock

    @pytest.fixture
    def orchestrator(self, mock_llm):
        """Create an orchestrator with mock LLM."""
        return AgentOrchestrator(llm=mock_llm)

    @pytest.mark.asyncio
    async def test_llm_route_handles_invalid_json_response(self, orchestrator, mock_llm, caplog):
        """Test that invalid JSON from LLM triggers fallback routing with logging."""
        # Return response that doesn't contain valid JSON
        mock_llm.complete.return_value = LLMResponse(
            content="This is not valid JSON at all, just some text",
            model="test-model",
        )

        capable = [
            ("agent_a", CapabilityResponse(
                agent_name="agent_a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="Can handle this request",
            )),
            ("agent_b", CapabilityResponse(
                agent_name="agent_b",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.7,
                reasoning="Can also handle",
            )),
        ]

        # Register mock agents
        orchestrator._agents = {
            "agent_a": Mock(),
            "agent_b": Mock(),
        }

        import logging
        with caplog.at_level(logging.WARNING):
            result = await orchestrator._llm_route(
                request={"task": "test"},
                intent="test intent",
                capable=capable,
            )

        # Should fall back to highest confidence agent
        assert result.selected_agents == ["agent_a"]
        assert "Fallback" in result.reasoning
        # Should log warning about invalid JSON
        assert "valid JSON" in caplog.text or "fallback" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_llm_route_handles_json_parse_error(self, orchestrator, mock_llm, caplog):
        """Test that JSON parse errors trigger fallback with logging."""
        # Return response with malformed JSON (missing closing brace)
        mock_llm.complete.return_value = LLMResponse(
            content='{"selected": ["agent_a", "reasoning": "incomplete json"',
            model="test-model",
        )

        capable = [
            ("agent_a", CapabilityResponse(
                agent_name="agent_a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.8,
                reasoning="Ready to handle",
            )),
        ]

        orchestrator._agents = {"agent_a": Mock()}

        import logging
        with caplog.at_level(logging.WARNING):
            result = await orchestrator._llm_route(
                request={"task": "test"},
                intent=None,
                capable=capable,
            )

        assert result.selected_agents == ["agent_a"]
        assert "Fallback" in result.reasoning

    @pytest.mark.asyncio
    async def test_llm_route_handles_api_error(self, orchestrator, mock_llm, caplog):
        """Test that LLM API errors trigger fallback with logging."""
        mock_llm.complete.side_effect = Exception("API connection failed")

        capable = [
            ("agent_a", CapabilityResponse(
                agent_name="agent_a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.8,
                reasoning="Ready",
            )),
        ]

        orchestrator._agents = {"agent_a": Mock()}

        import logging
        with caplog.at_level(logging.WARNING):
            result = await orchestrator._llm_route(
                request={"task": "test"},
                intent=None,
                capable=capable,
            )

        assert result.selected_agents == ["agent_a"]
        # Should log the error
        assert "API connection failed" in caplog.text or "failed unexpectedly" in caplog.text

    @pytest.mark.asyncio
    async def test_llm_route_success_path(self, orchestrator, mock_llm):
        """Test that valid LLM response is processed correctly."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"selected": ["agent_a"], "parallel": false, "reasoning": "Best fit"}',
            model="test-model",
        )

        capable = [
            ("agent_a", CapabilityResponse(
                agent_name="agent_a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="Can handle",
            )),
            ("agent_b", CapabilityResponse(
                agent_name="agent_b",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.7,
                reasoning="Also capable",
            )),
        ]

        orchestrator._agents = {
            "agent_a": Mock(),
            "agent_b": Mock(),
        }

        result = await orchestrator._llm_route(
            request={"task": "test"},
            intent="test",
            capable=capable,
        )

        # Should use LLM's selection
        assert result.selected_agents == ["agent_a"]
        assert result.reasoning == "Best fit"
        assert result.confidence == 0.8


class TestMCPServerErrorHandling:
    """Test MCP server configuration error handling."""

    def test_handles_missing_config_file(self, tmp_path, caplog):
        """Test graceful handling of missing MCP config."""
        from framework.runner.runner import AgentRunner
        from framework.graph.edge import GraphSpec
        from framework.graph import Goal

        # Create minimal agent structure
        agent_path = tmp_path / "test_agent"
        agent_path.mkdir()

        # Create minimal graph and goal
        graph = GraphSpec(
            id="test",
            goal_id="test-goal",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[],
            edges=[],
        )
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="Test",
            success_criteria=[],
            constraints=[],
        )

        # Create runner (will try to load MCP config)
        runner = AgentRunner(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=True,
        )

        # Config file doesn't exist - should not raise
        nonexistent_config = agent_path / "nonexistent_mcp.json"
        runner._load_mcp_servers_from_config(nonexistent_config)

        # Should not have registered any servers
        assert runner._tool_registry is not None

    def test_handles_invalid_json_config(self, tmp_path, caplog):
        """Test graceful handling of invalid JSON in config."""
        from framework.runner.runner import AgentRunner
        from framework.graph.edge import GraphSpec
        from framework.graph import Goal

        agent_path = tmp_path / "test_agent"
        agent_path.mkdir()

        # Create invalid JSON config
        config_path = agent_path / "mcp_servers.json"
        config_path.write_text("{ this is not valid json }")

        graph = GraphSpec(
            id="test",
            goal_id="test-goal",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[],
            edges=[],
        )
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="Test",
            success_criteria=[],
            constraints=[],
        )

        runner = AgentRunner(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=True,
        )

        import logging
        with caplog.at_level(logging.WARNING):
            runner._load_mcp_servers_from_config(config_path)

        assert "Invalid JSON" in caplog.text

    def test_handles_partial_server_failures(self, tmp_path, caplog):
        """Test that one failing server doesn't prevent others from loading."""
        from framework.runner.runner import AgentRunner
        from framework.graph.edge import GraphSpec
        from framework.graph import Goal

        agent_path = tmp_path / "test_agent"
        agent_path.mkdir()

        # Create valid JSON with multiple servers
        config_path = agent_path / "mcp_servers.json"
        config_path.write_text(json.dumps({
            "servers": [
                {"name": "good_server", "transport": "stdio", "command": "test"},
                {"name": "bad_server", "transport": "stdio", "command": "test"},
                {"name": "another_good", "transport": "stdio", "command": "test"},
            ]
        }))

        graph = GraphSpec(
            id="test",
            goal_id="test-goal",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[],
            edges=[],
        )
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="Test",
            success_criteria=[],
            constraints=[],
        )

        runner = AgentRunner(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=True,
        )

        # Mock the tool registry to fail on specific server
        original_register = runner._tool_registry.register_mcp_server

        def side_effect(config):
            if config["name"] == "bad_server":
                raise Exception("Connection refused")
            return original_register(config)

        runner._tool_registry.register_mcp_server = Mock(side_effect=side_effect)

        import logging
        with caplog.at_level(logging.WARNING):
            runner._load_mcp_servers_from_config(config_path)

        # Should have tried to register all 3
        assert runner._tool_registry.register_mcp_server.call_count == 3
        # Should log warning for the bad one
        assert "bad_server" in caplog.text

    def test_handles_empty_servers_list(self, tmp_path, caplog):
        """Test handling of config with empty servers list."""
        from framework.runner.runner import AgentRunner
        from framework.graph.edge import GraphSpec
        from framework.graph import Goal

        agent_path = tmp_path / "test_agent"
        agent_path.mkdir()

        # Create config with empty servers list
        config_path = agent_path / "mcp_servers.json"
        config_path.write_text(json.dumps({"servers": []}))

        graph = GraphSpec(
            id="test",
            goal_id="test-goal",
            entry_node="start",
            terminal_nodes=["end"],
            nodes=[],
            edges=[],
        )
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="Test",
            success_criteria=[],
            constraints=[],
        )

        runner = AgentRunner(
            agent_path=agent_path,
            graph=graph,
            goal=goal,
            mock_mode=True,
        )

        import logging
        with caplog.at_level(logging.DEBUG):
            runner._load_mcp_servers_from_config(config_path)

        assert "No MCP servers defined" in caplog.text


class TestAnthropicCredentialHandling:
    """Test Anthropic credential manager error handling."""

    def test_falls_back_to_env_var_when_aden_tools_not_installed(self, caplog, monkeypatch):
        """Test fallback to environment variable when aden_tools not available."""
        from framework.llm.anthropic import _get_api_key_from_credential_manager

        # Set up env var
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-from-env")

        import logging
        with caplog.at_level(logging.DEBUG):
            result = _get_api_key_from_credential_manager()

        # Should get key from environment
        assert result == "test-key-from-env"

    def test_returns_none_when_no_key_available(self, monkeypatch):
        """Test returns None when no API key is available."""
        from framework.llm.anthropic import _get_api_key_from_credential_manager

        # Remove env var
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = _get_api_key_from_credential_manager()
        assert result is None
