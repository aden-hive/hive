"""Tests for AgentOrchestrator LiteLLM integration.

Run with:
    cd core
    pytest tests/test_orchestrator.py -v
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider
from framework.runner.orchestrator import AgentOrchestrator
from framework.runner.protocol import (
    AgentMessage,
    CapabilityLevel,
    CapabilityResponse,
    MessageType,
)
from framework.runner.runner import AgentInfo


def create_mock_agent_info(name="test_agent", description="Test agent"):
    """Helper to create a mock AgentInfo with all required fields."""
    return AgentInfo(
        name=name,
        description=description,
        goal_name="test_goal",
        goal_description="Test goal description",
        node_count=1,
        edge_count=0,
        nodes=[],
        edges=[],
        entry_node="start",
        terminal_nodes=["end"],
        success_criteria=[],
        constraints=[],
        required_tools=[],
        has_tools_module=False,
    )


class TestOrchestratorLLMInitialization:
    """Test AgentOrchestrator LLM provider initialization."""

    def test_auto_creates_litellm_provider_when_no_llm_passed(self):
        """Test that LiteLLMProvider is auto-created when no llm is passed."""
        with patch.object(LiteLLMProvider, "__init__", return_value=None) as mock_init:
            orchestrator = AgentOrchestrator()

            mock_init.assert_called_once_with(model="claude-haiku-4-5-20251001")
            assert orchestrator._llm is not None

    def test_uses_custom_model_parameter(self):
        """Test that custom model parameter is passed to LiteLLMProvider."""
        with patch.object(LiteLLMProvider, "__init__", return_value=None) as mock_init:
            AgentOrchestrator(model="gpt-4o")

            mock_init.assert_called_once_with(model="gpt-4o")

    def test_supports_openai_model_names(self):
        """Test that OpenAI model names are supported."""
        with patch.object(LiteLLMProvider, "__init__", return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(model="gpt-4o-mini")

            mock_init.assert_called_once_with(model="gpt-4o-mini")
            assert orchestrator._model == "gpt-4o-mini"

    def test_supports_anthropic_model_names(self):
        """Test that Anthropic model names are supported."""
        with patch.object(LiteLLMProvider, "__init__", return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(model="claude-3-haiku-20240307")

            mock_init.assert_called_once_with(model="claude-3-haiku-20240307")
            assert orchestrator._model == "claude-3-haiku-20240307"

    def test_skips_auto_creation_when_llm_passed(self):
        """Test that auto-creation is skipped when llm is explicitly passed."""
        mock_llm = Mock(spec=LLMProvider)

        with patch.object(LiteLLMProvider, "__init__", return_value=None) as mock_init:
            orchestrator = AgentOrchestrator(llm=mock_llm)

            mock_init.assert_not_called()
            assert orchestrator._llm is mock_llm

    def test_model_attribute_stored_correctly(self):
        """Test that _model attribute is stored correctly."""
        with patch.object(LiteLLMProvider, "__init__", return_value=None):
            orchestrator = AgentOrchestrator(model="gemini/gemini-1.5-flash")

            assert orchestrator._model == "gemini/gemini-1.5-flash"


class TestOrchestratorLLMProviderType:
    """Test that orchestrator uses correct LLM provider type."""

    def test_llm_is_litellm_provider_instance(self):
        """Test that auto-created _llm is a LiteLLMProvider instance."""
        orchestrator = AgentOrchestrator()

        assert isinstance(orchestrator._llm, LiteLLMProvider)

    def test_llm_implements_llm_provider_interface(self):
        """Test that _llm implements LLMProvider interface."""
        orchestrator = AgentOrchestrator()

        assert isinstance(orchestrator._llm, LLMProvider)
        assert hasattr(orchestrator._llm, "complete")
        assert hasattr(orchestrator._llm, "complete_with_tools")


# ============================================================================
# Tests for agent registration and management
# ============================================================================


class TestAgentRegistration:
    """Test agent registration with the orchestrator."""

    def test_register_runner_adds_agent(self):
        """Test that register_runner adds agent to registry."""
        orchestrator = AgentOrchestrator()
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test_agent", description="Test agent description"
        )

        orchestrator.register_runner(
            name="agent1",
            runner=mock_runner,
            capabilities=["capability1", "capability2"],
            priority=10,
        )

        assert "agent1" in orchestrator._agents
        agent = orchestrator._agents["agent1"]
        assert agent.name == "agent1"
        assert agent.description == "Test agent description"
        assert agent.capabilities == ["capability1", "capability2"]
        assert agent.priority == 10

    def test_register_runner_default_values(self):
        """Test that register_runner uses default values correctly."""
        orchestrator = AgentOrchestrator()
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test_agent", description="Test description"
        )

        orchestrator.register_runner(name="agent1", runner=mock_runner)

        agent = orchestrator._agents["agent1"]
        assert agent.capabilities == []
        assert agent.priority == 0

    def test_register_runner_multiple_agents(self):
        """Test registering multiple agents."""
        orchestrator = AgentOrchestrator()

        for i in range(3):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        assert len(orchestrator._agents) == 3
        assert "agent0" in orchestrator._agents
        assert "agent1" in orchestrator._agents
        assert "agent2" in orchestrator._agents


class TestAgentListing:
    """Test agent listing and priority sorting."""

    def test_list_agents_returns_sorted_by_priority(self):
        """Test that list_agents returns agents sorted by priority (highest first)."""
        orchestrator = AgentOrchestrator()

        # Register agents with different priorities
        for i, priority in enumerate([5, 10, 1]):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            orchestrator.register_runner(
                name=f"agent{i}",
                runner=mock_runner,
                capabilities=[f"cap{i}"],
                priority=priority,
            )

        agents = orchestrator.list_agents()

        assert len(agents) == 3
        assert agents[0]["priority"] == 10  # agent1
        assert agents[1]["priority"] == 5  # agent0
        assert agents[2]["priority"] == 1  # agent2

    def test_list_agents_includes_all_fields(self):
        """Test that list_agents includes all required fields."""
        orchestrator = AgentOrchestrator()
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test", description="Test agent"
        )
        orchestrator.register_runner(
            name="agent1",
            runner=mock_runner,
            capabilities=["cap1", "cap2"],
            priority=5,
        )

        agents = orchestrator.list_agents()

        assert len(agents) == 1
        agent = agents[0]
        assert "name" in agent
        assert "description" in agent
        assert "capabilities" in agent
        assert "priority" in agent
        assert agent["name"] == "agent1"
        assert agent["description"] == "Test agent"
        assert agent["capabilities"] == ["cap1", "cap2"]
        assert agent["priority"] == 5

    def test_list_agents_empty_registry(self):
        """Test that list_agents returns empty list for empty registry."""
        orchestrator = AgentOrchestrator()
        agents = orchestrator.list_agents()
        assert agents == []


# ============================================================================
# Tests for message dispatching
# ============================================================================


class TestDispatch:
    """Test request dispatching to agents."""

    @pytest.mark.asyncio
    async def test_dispatch_no_capable_agents(self):
        """Test dispatch when no agents can handle request."""
        orchestrator = AgentOrchestrator()
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info()
        mock_runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.CANNOT_HANDLE,
                confidence=0.0,
                reasoning="Cannot handle this request",
            )
        )
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        result = await orchestrator.dispatch({"task": "test"})

        assert result.success is False
        assert result.handled_by == []
        assert result.error == "No agent capable of handling this request"

    @pytest.mark.asyncio
    async def test_dispatch_single_capable_agent(self):
        """Test dispatch with one capable agent."""
        orchestrator = AgentOrchestrator()
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test", description="Test"
        )
        mock_runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="I can handle this",
            )
        )
        mock_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE,
                from_agent="agent1",
                content={"result": "success"},
            )
        )
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        result = await orchestrator.dispatch({"task": "test"}, intent="test task")

        assert result.success is True
        assert result.handled_by == ["agent1"]
        assert "agent1" in result.results
        assert result.results["agent1"]["result"] == "success"

    @pytest.mark.asyncio
    async def test_dispatch_sequential_execution(self):
        """Test dispatch with sequential execution of multiple agents."""
        orchestrator = AgentOrchestrator()

        # Create two agents
        for i in range(2):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            mock_runner.can_handle = AsyncMock(
                return_value=CapabilityResponse(
                    agent_name=f"agent{i}",
                    level=CapabilityLevel.CAN_HANDLE,
                    confidence=0.8,
                    reasoning="Can handle",
                )
            )
            mock_runner.receive_message = AsyncMock(
                return_value=AgentMessage(
                    type=MessageType.RESPONSE,
                    from_agent=f"agent{i}",
                    content={"results": {f"step{i}": "done"}},
                )
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        # Mock LLM to select sequential processing
        with patch.object(orchestrator, "_llm_route", new_callable=AsyncMock) as mock_llm:
            from framework.runner.orchestrator import RoutingDecision

            mock_llm.return_value = RoutingDecision(
                selected_agents=["agent0", "agent1"],
                reasoning="Run sequentially",
                confidence=0.9,
                should_parallelize=False,
            )

            result = await orchestrator.dispatch({"task": "test"})

            assert result.success is True
            assert len(result.handled_by) == 2
            assert "agent0" in result.handled_by
            assert "agent1" in result.handled_by

    @pytest.mark.asyncio
    async def test_dispatch_parallel_execution(self):
        """Test dispatch with parallel execution of multiple agents."""
        orchestrator = AgentOrchestrator()

        # Create two agents
        for i in range(2):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            mock_runner.can_handle = AsyncMock(
                return_value=CapabilityResponse(
                    agent_name=f"agent{i}",
                    level=CapabilityLevel.CAN_HANDLE,
                    confidence=0.8,
                    reasoning="Can handle",
                )
            )
            mock_runner.receive_message = AsyncMock(
                return_value=AgentMessage(
                    type=MessageType.RESPONSE,
                    from_agent=f"agent{i}",
                    content={"result": f"parallel_{i}"},
                )
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        # Mock LLM to select parallel processing
        with patch.object(orchestrator, "_llm_route", new_callable=AsyncMock) as mock_llm:
            from framework.runner.orchestrator import RoutingDecision

            mock_llm.return_value = RoutingDecision(
                selected_agents=["agent0", "agent1"],
                reasoning="Run in parallel",
                confidence=0.9,
                should_parallelize=True,
            )

            result = await orchestrator.dispatch({"task": "test"})

            assert result.success is True
            assert len(result.handled_by) == 2
            assert "agent0" in result.results
            assert "agent1" in result.results

    @pytest.mark.asyncio
    async def test_dispatch_handles_agent_error(self):
        """Test dispatch gracefully handles agent errors."""
        orchestrator = AgentOrchestrator()
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test", description="Test"
        )
        mock_runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="Can handle",
            )
        )
        mock_runner.receive_message = AsyncMock(side_effect=Exception("Agent error"))
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        result = await orchestrator.dispatch({"task": "test"})

        assert "agent1" in result.results
        assert "error" in result.results["agent1"]

    @pytest.mark.asyncio
    async def test_dispatch_with_fallback_agents(self):
        """Test dispatch tries fallback agents on error."""
        orchestrator = AgentOrchestrator()

        # Create main and fallback agents
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="main", description="Main"
        )
        mock_runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.5,
                reasoning="Uncertain",
            )
        )
        mock_runner.receive_message = AsyncMock(side_effect=Exception("Error"))
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        fallback_runner = Mock()
        fallback_runner.info.return_value = create_mock_agent_info(
            name="fallback", description="Fallback"
        )
        fallback_runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="agent2",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.4,
                reasoning="Might work",
            )
        )
        fallback_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE,
                from_agent="agent2",
                content={"result": "fallback success"},
            )
        )
        orchestrator.register_runner(name="agent2", runner=fallback_runner)

        result = await orchestrator.dispatch({"task": "test"})

        # Should have tried agent1 (failed) and agent2 (succeeded)
        assert "agent1" in result.results
        assert "agent2" in result.results


# ============================================================================
# Tests for message relay
# ============================================================================


class TestRelay:
    """Test agent-to-agent message relay."""

    @pytest.mark.asyncio
    async def test_relay_sends_message_between_agents(self):
        """Test that relay successfully sends message from one agent to another."""
        orchestrator = AgentOrchestrator()

        # Register target agent
        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="target", description="Target"
        )
        mock_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE,
                from_agent="agent2",
                content={"status": "received"},
            )
        )
        orchestrator.register_runner(name="agent2", runner=mock_runner)

        response = await orchestrator.relay(
            from_agent="agent1",
            to_agent="agent2",
            content={"data": "test"},
            intent="relay test",
        )

        assert response.from_agent == "agent2"
        assert response.content["status"] == "received"
        mock_runner.receive_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_relay_logs_messages(self):
        """Test that relay logs both request and response messages."""
        orchestrator = AgentOrchestrator()

        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="target", description="Target"
        )
        mock_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE, from_agent="agent2", content={}
            )
        )
        orchestrator.register_runner(name="agent2", runner=mock_runner)

        await orchestrator.relay(
            from_agent="agent1", to_agent="agent2", content={}, intent="test"
        )

        log = orchestrator.get_message_log()
        assert len(log) >= 2  # At least request and response

    @pytest.mark.asyncio
    async def test_relay_raises_error_for_unknown_agent(self):
        """Test that relay raises ValueError for unknown target agent."""
        orchestrator = AgentOrchestrator()

        with pytest.raises(ValueError, match="Unknown agent: unknown"):
            await orchestrator.relay(
                from_agent="agent1",
                to_agent="unknown",
                content={},
                intent="test",
            )


# ============================================================================
# Tests for broadcast
# ============================================================================


class TestBroadcast:
    """Test broadcasting messages to all agents."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_agents(self):
        """Test that broadcast sends message to all registered agents."""
        orchestrator = AgentOrchestrator()

        # Register multiple agents
        for i in range(3):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            mock_runner.receive_message = AsyncMock(
                return_value=AgentMessage(
                    type=MessageType.RESPONSE,
                    from_agent=f"agent{i}",
                    content={"received": True},
                )
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        responses = await orchestrator.broadcast(
            content={"message": "hello"}, intent="test broadcast"
        )

        assert len(responses) == 3
        assert "agent0" in responses
        assert "agent1" in responses
        assert "agent2" in responses

    @pytest.mark.asyncio
    async def test_broadcast_with_exclusion(self):
        """Test that broadcast respects exclusion list."""
        orchestrator = AgentOrchestrator()

        # Register multiple agents
        for i in range(3):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            mock_runner.receive_message = AsyncMock(
                return_value=AgentMessage(
                    type=MessageType.RESPONSE, from_agent=f"agent{i}", content={}
                )
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        responses = await orchestrator.broadcast(
            content={"message": "hello"}, intent="test", exclude=["agent1"]
        )

        assert len(responses) == 2
        assert "agent0" in responses
        assert "agent1" not in responses
        assert "agent2" in responses

    @pytest.mark.asyncio
    async def test_broadcast_handles_agent_errors(self):
        """Test that broadcast handles agent errors gracefully."""
        orchestrator = AgentOrchestrator()

        # Register agents, one that will fail
        good_runner = Mock()
        good_runner.info.return_value = create_mock_agent_info(
            name="good", description="Good"
        )
        good_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE, from_agent="agent1", content={}
            )
        )
        orchestrator.register_runner(name="agent1", runner=good_runner)

        bad_runner = Mock()
        bad_runner.info.return_value = create_mock_agent_info(
            name="bad", description="Bad"
        )
        bad_runner.receive_message = AsyncMock(side_effect=Exception("Error"))
        orchestrator.register_runner(name="agent2", runner=bad_runner)

        responses = await orchestrator.broadcast(content={})

        assert len(responses) == 2
        assert "agent1" in responses
        assert "agent2" in responses
        assert "error" in responses["agent2"].content


# ============================================================================
# Tests for routing logic
# ============================================================================


class TestRouting:
    """Test request routing decision logic."""

    @pytest.mark.asyncio
    async def test_route_request_single_capable_agent(self):
        """Test routing when only one agent can handle request."""
        orchestrator = AgentOrchestrator()

        capabilities = {
            "agent1": CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="I can do this",
            ),
            "agent2": CapabilityResponse(
                agent_name="agent2",
                level=CapabilityLevel.CANNOT_HANDLE,
                confidence=0.0,
                reasoning="Not for me",
            ),
        }

        routing = await orchestrator._route_request({}, None, capabilities)

        assert routing.selected_agents == ["agent1"]
        assert routing.reasoning == "I can do this"
        assert routing.confidence == 0.9

    @pytest.mark.asyncio
    async def test_route_request_uncertain_agents(self):
        """Test routing falls back to uncertain agents when no capable agents."""
        orchestrator = AgentOrchestrator()

        capabilities = {
            "agent1": CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.5,
                reasoning="Maybe",
            ),
            "agent2": CapabilityResponse(
                agent_name="agent2",
                level=CapabilityLevel.CANNOT_HANDLE,
                confidence=0.0,
                reasoning="No",
            ),
        }

        routing = await orchestrator._route_request({}, None, capabilities)

        assert "agent1" in routing.selected_agents
        assert "Uncertain match" in routing.reasoning

    @pytest.mark.asyncio
    async def test_route_request_no_capable_agents(self):
        """Test routing when no agents can handle request."""
        orchestrator = AgentOrchestrator()

        capabilities = {
            "agent1": CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.CANNOT_HANDLE,
                confidence=0.0,
                reasoning="Cannot",
            ),
        }

        routing = await orchestrator._route_request({}, None, capabilities)

        assert routing.selected_agents == []
        assert routing.reasoning == "No capable agents found"

    @pytest.mark.asyncio
    async def test_llm_route_with_valid_response(self):
        """Test LLM routing with valid JSON response."""
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = '{"selected": ["agent1"], "parallel": false, "reasoning": "Best fit"}'
        mock_llm.complete.return_value = mock_response

        orchestrator = AgentOrchestrator(llm=mock_llm)

        # Register agents so validation passes
        for i in range(2):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        capable = [
            (
                "agent1",
                CapabilityResponse(
                    agent_name="agent1",
                    level=CapabilityLevel.CAN_HANDLE,
                    confidence=0.9,
                    reasoning="Can do",
                ),
            ),
        ]

        routing = await orchestrator._llm_route({}, "test", capable)

        assert routing.selected_agents == ["agent1"]
        assert routing.reasoning == "Best fit"
        assert not routing.should_parallelize

    @pytest.mark.asyncio
    async def test_llm_route_fallback_on_error(self):
        """Test LLM routing falls back to highest confidence on error."""
        mock_llm = Mock()
        mock_llm.complete.side_effect = Exception("LLM error")

        orchestrator = AgentOrchestrator(llm=mock_llm)

        capable = [
            (
                "agent1",
                CapabilityResponse(
                    agent_name="agent1",
                    level=CapabilityLevel.BEST_FIT,
                    confidence=0.95,
                    reasoning="Best",
                ),
            ),
            (
                "agent2",
                CapabilityResponse(
                    agent_name="agent2",
                    level=CapabilityLevel.CAN_HANDLE,
                    confidence=0.7,
                    reasoning="Ok",
                ),
            ),
        ]

        routing = await orchestrator._llm_route({}, "test", capable)

        assert routing.selected_agents == ["agent1"]
        assert routing.confidence == 0.95


# ============================================================================
# Tests for capability checking
# ============================================================================


class TestCapabilityChecking:
    """Test parallel capability checking."""

    @pytest.mark.asyncio
    async def test_check_all_capabilities_success(self):
        """Test checking capabilities of all agents successfully."""
        orchestrator = AgentOrchestrator()

        # Register agents
        for i in range(2):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            mock_runner.can_handle = AsyncMock(
                return_value=CapabilityResponse(
                    agent_name=f"agent{i}",
                    level=CapabilityLevel.CAN_HANDLE,
                    confidence=0.8,
                    reasoning="Yes",
                )
            )
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)

        capabilities = await orchestrator._check_all_capabilities({"task": "test"})

        assert len(capabilities) == 2
        assert "agent0" in capabilities
        assert "agent1" in capabilities
        assert capabilities["agent0"].level == CapabilityLevel.CAN_HANDLE

    @pytest.mark.asyncio
    async def test_check_all_capabilities_handles_errors(self):
        """Test capability checking handles agent errors gracefully."""
        orchestrator = AgentOrchestrator()

        # Register good and bad agents
        good_runner = Mock()
        good_runner.info.return_value = create_mock_agent_info(
            name="good", description="Good"
        )
        good_runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="agent1",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.8,
                reasoning="Yes",
            )
        )
        orchestrator.register_runner(name="agent1", runner=good_runner)

        bad_runner = Mock()
        bad_runner.info.return_value = create_mock_agent_info(
            name="bad", description="Bad"
        )
        bad_runner.can_handle = AsyncMock(side_effect=Exception("Check failed"))
        orchestrator.register_runner(name="agent2", runner=bad_runner)

        capabilities = await orchestrator._check_all_capabilities({})

        assert len(capabilities) == 2
        assert capabilities["agent1"].level == CapabilityLevel.CAN_HANDLE
        assert capabilities["agent2"].level == CapabilityLevel.CANNOT_HANDLE
        assert "Error" in capabilities["agent2"].reasoning


# ============================================================================
# Tests for message log operations
# ============================================================================


class TestMessageLog:
    """Test message logging operations."""

    @pytest.mark.asyncio
    async def test_get_message_log_returns_copy(self):
        """Test that get_message_log returns a copy of messages."""
        orchestrator = AgentOrchestrator()

        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test", description="Test"
        )
        mock_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE, from_agent="agent1", content={}
            )
        )
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        await orchestrator.relay(
            from_agent="source", to_agent="agent1", content={}, intent="test"
        )

        log1 = orchestrator.get_message_log()
        log2 = orchestrator.get_message_log()

        assert log1 is not log2  # Different list objects
        assert len(log1) == len(log2)

    @pytest.mark.asyncio
    async def test_clear_message_log(self):
        """Test that clear_message_log removes all messages."""
        orchestrator = AgentOrchestrator()

        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test", description="Test"
        )
        mock_runner.receive_message = AsyncMock(
            return_value=AgentMessage(
                type=MessageType.RESPONSE, from_agent="agent1", content={}
            )
        )
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        await orchestrator.relay(
            from_agent="source", to_agent="agent1", content={}, intent="test"
        )

        assert len(orchestrator.get_message_log()) > 0

        orchestrator.clear_message_log()

        assert len(orchestrator.get_message_log()) == 0

    def test_message_log_initially_empty(self):
        """Test that message log starts empty."""
        orchestrator = AgentOrchestrator()
        log = orchestrator.get_message_log()
        assert log == []


# ============================================================================
# Tests for cleanup
# ============================================================================


class TestCleanup:
    """Test resource cleanup."""

    def test_cleanup_calls_runner_cleanup(self):
        """Test that cleanup calls cleanup on all runners."""
        orchestrator = AgentOrchestrator()

        # Register multiple agents
        mock_runners = []
        for i in range(3):
            mock_runner = Mock()
            mock_runner.info.return_value = create_mock_agent_info(
                name=f"agent{i}", description=f"Agent {i}"
            )
            mock_runner.cleanup = Mock()
            orchestrator.register_runner(name=f"agent{i}", runner=mock_runner)
            mock_runners.append(mock_runner)

        orchestrator.cleanup()

        # All runners should have cleanup called
        for runner in mock_runners:
            runner.cleanup.assert_called_once()

    def test_cleanup_clears_agent_registry(self):
        """Test that cleanup clears the agent registry."""
        orchestrator = AgentOrchestrator()

        mock_runner = Mock()
        mock_runner.info.return_value = create_mock_agent_info(
            name="test", description="Test"
        )
        mock_runner.cleanup = Mock()
        orchestrator.register_runner(name="agent1", runner=mock_runner)

        assert len(orchestrator._agents) == 1

        orchestrator.cleanup()

        assert len(orchestrator._agents) == 0

    def test_cleanup_on_empty_registry(self):
        """Test that cleanup works on empty registry."""
        orchestrator = AgentOrchestrator()
        orchestrator.cleanup()  # Should not raise
        assert len(orchestrator._agents) == 0
