"""Tests for AgentOrchestrator.

Covers LLM initialization, agent registration, routing, dispatch,
relay, broadcast, message logging, and cleanup.

Run with:
    cd core
    pytest tests/test_orchestrator.py -v
"""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock, patch

import pytest

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider
from framework.runner.orchestrator import AgentOrchestrator, RoutingDecision
from framework.runner.protocol import (
    AgentMessage,
    CapabilityLevel,
    CapabilityResponse,
    MessageType,
    OrchestratorResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_runner(name: str = "agent", description: str = "A test agent"):
    """Create a mock AgentRunner with standard stubs."""
    runner = Mock()
    runner.info.return_value = Mock(name=name, description=description)
    runner.can_handle = AsyncMock(
        return_value=CapabilityResponse(
            agent_name=name,
            level=CapabilityLevel.CAN_HANDLE,
            confidence=0.9,
            reasoning="I can handle this",
        )
    )
    runner.receive_message = AsyncMock(
        side_effect=lambda msg: AgentMessage(
            type=MessageType.RESPONSE,
            from_agent=name,
            to_agent="orchestrator",
            content={"results": {"handled": True}},
            parent_id=msg.id,
        )
    )
    runner.cleanup = Mock()
    return runner


def _make_orchestrator_with_agents(**agent_kwargs):
    """Return an orchestrator with pre-registered mock agents.

    Usage:
        orch = _make_orchestrator_with_agents(
            sales={"description": "Sales agent", "priority": 2},
            support={"description": "Support agent"},
        )
    """
    llm = Mock(spec=LLMProvider)
    orch = AgentOrchestrator(llm=llm)
    for name, kwargs in agent_kwargs.items():
        desc = kwargs.get("description", f"{name} agent")
        priority = kwargs.get("priority", 0)
        caps = kwargs.get("capabilities", [])
        runner = _make_mock_runner(name=name, description=desc)
        orch.register_runner(name, runner, capabilities=caps, priority=priority)
    return orch


# ===================================================================
# Existing: LLM Initialization
# ===================================================================


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


# ===================================================================
# Agent Registration
# ===================================================================


class TestRegisterRunner:
    """Test registering agents via register_runner."""

    def test_register_single_agent(self):
        """A single agent should appear in the internal registry."""
        orch = _make_orchestrator_with_agents(alpha={})
        assert "alpha" in orch._agents

    def test_register_multiple_agents(self):
        """All agents passed should be registered."""
        orch = _make_orchestrator_with_agents(a={}, b={}, c={})
        assert set(orch._agents.keys()) == {"a", "b", "c"}

    def test_capabilities_stored(self):
        """Capabilities passed at registration should be persisted."""
        orch = _make_orchestrator_with_agents(
            sales={"capabilities": ["crm", "outreach"]}
        )
        assert orch._agents["sales"].capabilities == ["crm", "outreach"]

    def test_priority_stored(self):
        """Priority passed at registration should be persisted."""
        orch = _make_orchestrator_with_agents(sales={"priority": 5})
        assert orch._agents["sales"].priority == 5

    def test_default_priority_is_zero(self):
        """Default priority should be 0 when not specified."""
        orch = _make_orchestrator_with_agents(sales={})
        assert orch._agents["sales"].priority == 0

    def test_default_capabilities_is_empty(self):
        """Default capabilities should be an empty list."""
        orch = _make_orchestrator_with_agents(sales={})
        assert orch._agents["sales"].capabilities == []

    def test_overwrite_existing_agent(self):
        """Re-registering with the same name should overwrite the entry."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner_v1 = _make_mock_runner(name="alpha", description="v1")
        runner_v2 = _make_mock_runner(name="alpha", description="v2")

        orch.register_runner("alpha", runner_v1)
        orch.register_runner("alpha", runner_v2)

        assert orch._agents["alpha"].runner is runner_v2


# ===================================================================
# list_agents
# ===================================================================


class TestListAgents:
    """Test listing registered agents."""

    def test_empty_registry(self):
        """Listing on an empty orchestrator should return an empty list."""
        orch = AgentOrchestrator(llm=Mock(spec=LLMProvider))
        assert orch.list_agents() == []

    def test_returns_all_agents(self):
        """All registered agents should appear in the listing."""
        orch = _make_orchestrator_with_agents(a={}, b={}, c={})
        names = [a["name"] for a in orch.list_agents()]
        assert set(names) == {"a", "b", "c"}

    def test_sorted_by_priority_descending(self):
        """Agents should be listed with highest priority first."""
        orch = _make_orchestrator_with_agents(
            low={"priority": 1},
            mid={"priority": 5},
            high={"priority": 10},
        )
        names = [a["name"] for a in orch.list_agents()]
        assert names == ["high", "mid", "low"]

    def test_listing_contains_expected_keys(self):
        """Each entry should have name, description, capabilities, priority."""
        orch = _make_orchestrator_with_agents(
            sales={"capabilities": ["crm"], "priority": 3}
        )
        entry = orch.list_agents()[0]
        assert set(entry.keys()) == {"name", "description", "capabilities", "priority"}


# ===================================================================
# Dispatch
# ===================================================================


class TestDispatch:
    """Test request dispatching to agent(s)."""

    @pytest.mark.asyncio
    async def test_dispatch_single_capable_agent(self):
        """A single capable agent should handle the request successfully."""
        orch = _make_orchestrator_with_agents(sales={})
        result = await orch.dispatch({"task": "sell"}, intent="sell stuff")

        assert result.success is True
        assert "sales" in result.handled_by
        assert "sales" in result.results

    @pytest.mark.asyncio
    async def test_dispatch_returns_orchestrator_result(self):
        """dispatch should return an OrchestratorResult."""
        orch = _make_orchestrator_with_agents(sales={})
        result = await orch.dispatch({"task": "sell"})
        assert isinstance(result, OrchestratorResult)

    @pytest.mark.asyncio
    async def test_dispatch_no_capable_agents(self):
        """When no agent can handle the request, result should indicate failure."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner = _make_mock_runner()
        runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="nope",
                level=CapabilityLevel.CANNOT_HANDLE,
                confidence=0.0,
                reasoning="Not my job",
            )
        )
        orch.register_runner("nope", runner)

        result = await orch.dispatch({"task": "impossible"})

        assert result.success is False
        assert result.handled_by == []
        assert result.error == "No agent capable of handling this request"

    @pytest.mark.asyncio
    async def test_dispatch_empty_registry(self):
        """Dispatching with no registered agents should fail gracefully."""
        orch = AgentOrchestrator(llm=Mock(spec=LLMProvider))
        result = await orch.dispatch({"task": "anything"})

        assert result.success is False
        assert result.handled_by == []

    @pytest.mark.asyncio
    async def test_dispatch_sequential_accumulates_context(self):
        """Sequential dispatch should pass accumulated results to next agent."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        received_contents = []

        async def capture_message(msg):
            received_contents.append(dict(msg.content))
            return AgentMessage(
                type=MessageType.RESPONSE,
                from_agent="agent",
                content={"results": {"step": "done"}},
                parent_id=msg.id,
            )

        runner_a = _make_mock_runner(name="a")
        runner_a.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.95,
                reasoning="Yes",
            )
        )
        runner_a.receive_message = AsyncMock(side_effect=capture_message)

        runner_b = _make_mock_runner(name="b")
        runner_b.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="b",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.85,
                reasoning="Yes too",
            )
        )
        runner_b.receive_message = AsyncMock(side_effect=capture_message)

        orch.register_runner("a", runner_a)
        orch.register_runner("b", runner_b)

        # Patch _route_request to force sequential multi-agent routing
        async def forced_route(request, intent, caps):
            return RoutingDecision(
                selected_agents=["a", "b"],
                reasoning="both needed",
                confidence=0.9,
                should_parallelize=False,
            )

        orch._route_request = forced_route

        await orch.dispatch({"task": "pipeline"})

        # Second agent should have received accumulated context from first
        assert len(received_contents) == 2
        assert "step" in received_contents[1]

    @pytest.mark.asyncio
    async def test_dispatch_handles_agent_exception(self):
        """If an agent raises, the error should be captured in results."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner = _make_mock_runner(name="flaky")
        runner.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="flaky",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="Sure",
            )
        )
        runner.receive_message = AsyncMock(side_effect=RuntimeError("boom"))
        orch.register_runner("flaky", runner)

        result = await orch.dispatch({"task": "explode"})

        assert "flaky" in result.results
        assert "error" in result.results["flaky"]
        assert "boom" in result.results["flaky"]["error"]

    @pytest.mark.asyncio
    async def test_dispatch_fallback_on_failure(self):
        """When primary agent fails and fallback exists, fallback should run."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner_primary = _make_mock_runner(name="primary")
        runner_primary.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="primary",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.6,
                reasoning="Maybe",
            )
        )
        runner_primary.receive_message = AsyncMock(
            side_effect=RuntimeError("primary failed")
        )

        runner_backup = _make_mock_runner(name="backup")
        runner_backup.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="backup",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.4,
                reasoning="I can try",
            )
        )

        orch.register_runner("primary", runner_primary)
        orch.register_runner("backup", runner_backup)

        result = await orch.dispatch({"task": "risky"})

        # Backup should have been tried after primary failed
        assert "backup" in result.handled_by

    @pytest.mark.asyncio
    async def test_dispatch_messages_list_populated(self):
        """dispatch should return a non-empty messages trace."""
        orch = _make_orchestrator_with_agents(sales={})
        result = await orch.dispatch({"task": "sell"})

        assert len(result.messages) > 0
        assert all(isinstance(m, AgentMessage) for m in result.messages)

    @pytest.mark.asyncio
    async def test_dispatch_parallel_execution(self):
        """When routing says parallelize, agents should run concurrently."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner_a = _make_mock_runner(name="a")
        runner_a.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="Yes",
            )
        )

        runner_b = _make_mock_runner(name="b")
        runner_b.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="b",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.85,
                reasoning="Yes too",
            )
        )

        orch.register_runner("a", runner_a)
        orch.register_runner("b", runner_b)

        # Force parallel routing
        async def forced_route(request, intent, caps):
            return RoutingDecision(
                selected_agents=["a", "b"],
                reasoning="parallel",
                confidence=0.9,
                should_parallelize=True,
            )

        orch._route_request = forced_route

        result = await orch.dispatch({"task": "parallel work"})

        assert result.success is True
        assert set(result.handled_by) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_dispatch_parallel_captures_exceptions(self):
        """In parallel mode, individual agent errors should be captured."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner_ok = _make_mock_runner(name="ok")
        runner_ok.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="ok",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.9,
                reasoning="Yes",
            )
        )

        runner_fail = _make_mock_runner(name="fail")
        runner_fail.can_handle = AsyncMock(
            return_value=CapabilityResponse(
                agent_name="fail",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.85,
                reasoning="Yes",
            )
        )
        runner_fail.receive_message = AsyncMock(side_effect=RuntimeError("crash"))

        orch.register_runner("ok", runner_ok)
        orch.register_runner("fail", runner_fail)

        async def forced_route(request, intent, caps):
            return RoutingDecision(
                selected_agents=["ok", "fail"],
                reasoning="parallel",
                confidence=0.9,
                should_parallelize=True,
            )

        orch._route_request = forced_route

        result = await orch.dispatch({"task": "mixed"})

        assert "ok" in result.handled_by
        assert "fail" not in result.handled_by
        assert "error" in result.results["fail"]


# ===================================================================
# Relay
# ===================================================================


class TestRelay:
    """Test agent-to-agent message relay."""

    @pytest.mark.asyncio
    async def test_relay_success(self):
        """Relay should deliver message and return a response."""
        orch = _make_orchestrator_with_agents(support={})
        response = await orch.relay("sales", "support", {"issue": "billing"})

        assert isinstance(response, AgentMessage)
        assert response.type == MessageType.RESPONSE

    @pytest.mark.asyncio
    async def test_relay_unknown_target_raises(self):
        """Relaying to a non-existent agent should raise ValueError."""
        orch = _make_orchestrator_with_agents(sales={})
        with pytest.raises(ValueError, match="Unknown agent: ghost"):
            await orch.relay("sales", "ghost", {"msg": "hello"})

    @pytest.mark.asyncio
    async def test_relay_logs_messages(self):
        """Both the outgoing message and response should be logged."""
        orch = _make_orchestrator_with_agents(support={})
        orch.clear_message_log()

        await orch.relay("sales", "support", {"issue": "billing"})

        log = orch.get_message_log()
        assert len(log) == 2
        assert log[0].type == MessageType.HANDOFF
        assert log[1].type == MessageType.RESPONSE

    @pytest.mark.asyncio
    async def test_relay_message_fields(self):
        """Relayed message should have correct from/to/intent fields."""
        orch = _make_orchestrator_with_agents(support={})
        orch.clear_message_log()

        await orch.relay("sales", "support", {"x": 1}, intent="help me")

        msg = orch.get_message_log()[0]
        assert msg.from_agent == "sales"
        assert msg.to_agent == "support"
        assert msg.intent == "help me"
        assert msg.content == {"x": 1}


# ===================================================================
# Broadcast
# ===================================================================


class TestBroadcast:
    """Test broadcasting messages to all agents."""

    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_agents(self):
        """Broadcast should send to every registered agent."""
        orch = _make_orchestrator_with_agents(a={}, b={}, c={})
        responses = await orch.broadcast({"alert": "update"})

        assert set(responses.keys()) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_broadcast_excludes_specified_agents(self):
        """Agents in the exclude list should not receive the broadcast."""
        orch = _make_orchestrator_with_agents(a={}, b={}, c={})
        responses = await orch.broadcast({"alert": "update"}, exclude=["b"])

        assert "b" not in responses
        assert set(responses.keys()) == {"a", "c"}

    @pytest.mark.asyncio
    async def test_broadcast_handles_agent_exception(self):
        """If one agent fails during broadcast, others should still work."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner_ok = _make_mock_runner(name="ok")
        runner_fail = _make_mock_runner(name="fail")
        runner_fail.receive_message = AsyncMock(side_effect=RuntimeError("down"))

        orch.register_runner("ok", runner_ok)
        orch.register_runner("fail", runner_fail)

        responses = await orch.broadcast({"ping": True})

        assert "ok" in responses
        assert "fail" in responses
        assert responses["fail"].content == {"error": "down"}

    @pytest.mark.asyncio
    async def test_broadcast_empty_registry(self):
        """Broadcasting with no agents should return an empty dict."""
        orch = AgentOrchestrator(llm=Mock(spec=LLMProvider))
        responses = await orch.broadcast({"ping": True})
        assert responses == {}


# ===================================================================
# Routing Logic
# ===================================================================


class TestRouting:
    """Test internal routing decision logic."""

    @pytest.mark.asyncio
    async def test_single_capable_agent_selected(self):
        """A single BEST_FIT agent should be selected without LLM routing."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        caps = {
            "alpha": CapabilityResponse(
                agent_name="alpha",
                level=CapabilityLevel.BEST_FIT,
                confidence=0.95,
                reasoning="Perfect match",
            ),
        }

        decision = await orch._route_request({}, None, caps)

        assert decision.selected_agents == ["alpha"]
        assert decision.confidence == 0.95

    @pytest.mark.asyncio
    async def test_no_capable_agents_returns_empty(self):
        """When all agents CANNOT_HANDLE, selected_agents should be empty."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        caps = {
            "a": CapabilityResponse(
                agent_name="a",
                level=CapabilityLevel.CANNOT_HANDLE,
                confidence=0.0,
                reasoning="No",
            ),
        }

        decision = await orch._route_request({}, None, caps)

        assert decision.selected_agents == []

    @pytest.mark.asyncio
    async def test_uncertain_agents_used_as_fallback(self):
        """When no capable agents exist, uncertain ones should be tried."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        caps = {
            "maybe1": CapabilityResponse(
                agent_name="maybe1",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.5,
                reasoning="Might work",
            ),
            "maybe2": CapabilityResponse(
                agent_name="maybe2",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.3,
                reasoning="Perhaps",
            ),
        }

        decision = await orch._route_request({}, None, caps)

        assert decision.selected_agents == ["maybe1"]
        assert "maybe2" in decision.fallback_agents

    @pytest.mark.asyncio
    async def test_uncertain_sorted_by_confidence(self):
        """Among uncertain agents, highest confidence should be primary."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        caps = {
            "low": CapabilityResponse(
                agent_name="low",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.2,
                reasoning="Low",
            ),
            "high": CapabilityResponse(
                agent_name="high",
                level=CapabilityLevel.UNCERTAIN,
                confidence=0.7,
                reasoning="High",
            ),
        }

        decision = await orch._route_request({}, None, caps)

        assert decision.selected_agents == ["high"]

    @pytest.mark.asyncio
    async def test_multiple_capable_agents_triggers_llm_routing(self):
        """When multiple agents are capable, _llm_route should be called."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        caps = {
            "a": CapabilityResponse(
                agent_name="a",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.8,
                reasoning="Can do",
            ),
            "b": CapabilityResponse(
                agent_name="b",
                level=CapabilityLevel.CAN_HANDLE,
                confidence=0.75,
                reasoning="Also can do",
            ),
        }

        # Register mock agents so _llm_route validation works
        for name in ("a", "b"):
            orch.register_runner(name, _make_mock_runner(name=name))

        # Mock LLM to return valid routing JSON
        llm.complete = Mock(
            return_value=Mock(
                content='{"selected": ["a"], "parallel": false, "reasoning": "a is better"}'
            )
        )

        decision = await orch._route_request({}, "test", caps)

        assert "a" in decision.selected_agents


# ===================================================================
# LLM Routing
# ===================================================================


class TestLLMRoute:
    """Test LLM-based routing when multiple agents are capable."""

    @pytest.mark.asyncio
    async def test_llm_route_parses_json_response(self):
        """Valid LLM JSON response should be parsed into a RoutingDecision."""
        llm = Mock(spec=LLMProvider)
        llm.complete = Mock(
            return_value=Mock(
                content='{"selected": ["sales"], "parallel": false, "reasoning": "best fit"}'
            )
        )
        orch = AgentOrchestrator(llm=llm)
        orch.register_runner("sales", _make_mock_runner(name="sales"))

        capable = [
            (
                "sales",
                CapabilityResponse(
                    agent_name="sales",
                    level=CapabilityLevel.CAN_HANDLE,
                    confidence=0.9,
                    reasoning="Good",
                ),
            ),
        ]

        decision = await orch._llm_route({}, "sell", capable)

        assert decision.selected_agents == ["sales"]
        assert decision.should_parallelize is False

    @pytest.mark.asyncio
    async def test_llm_route_parallel_flag(self):
        """LLM returning parallel=true should set should_parallelize."""
        llm = Mock(spec=LLMProvider)
        llm.complete = Mock(
            return_value=Mock(
                content='{"selected": ["a", "b"], "parallel": true, "reasoning": "both needed"}'
            )
        )
        orch = AgentOrchestrator(llm=llm)
        orch.register_runner("a", _make_mock_runner(name="a"))
        orch.register_runner("b", _make_mock_runner(name="b"))

        capable = [
            ("a", CapabilityResponse(agent_name="a", level=CapabilityLevel.CAN_HANDLE, confidence=0.9, reasoning="Yes")),
            ("b", CapabilityResponse(agent_name="b", level=CapabilityLevel.CAN_HANDLE, confidence=0.8, reasoning="Yes")),
        ]

        decision = await orch._llm_route({}, "test", capable)

        assert decision.should_parallelize is True
        assert set(decision.selected_agents) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_llm_route_filters_unknown_agents(self):
        """Agents returned by LLM but not registered should be filtered out."""
        llm = Mock(spec=LLMProvider)
        llm.complete = Mock(
            return_value=Mock(
                content='{"selected": ["real", "hallucinated"], "parallel": false, "reasoning": "both"}'
            )
        )
        orch = AgentOrchestrator(llm=llm)
        orch.register_runner("real", _make_mock_runner(name="real"))

        capable = [
            ("real", CapabilityResponse(agent_name="real", level=CapabilityLevel.CAN_HANDLE, confidence=0.9, reasoning="Yes")),
        ]

        decision = await orch._llm_route({}, "test", capable)

        assert decision.selected_agents == ["real"]
        assert "hallucinated" not in decision.selected_agents

    @pytest.mark.asyncio
    async def test_llm_route_fallback_on_invalid_json(self):
        """If LLM returns garbage, fallback to highest confidence agent."""
        llm = Mock(spec=LLMProvider)
        llm.complete = Mock(return_value=Mock(content="not valid json at all"))
        orch = AgentOrchestrator(llm=llm)

        capable = [
            ("best", CapabilityResponse(agent_name="best", level=CapabilityLevel.CAN_HANDLE, confidence=0.95, reasoning="Top")),
            ("other", CapabilityResponse(agent_name="other", level=CapabilityLevel.CAN_HANDLE, confidence=0.7, reasoning="Ok")),
        ]

        decision = await orch._llm_route({}, "test", capable)

        assert decision.selected_agents == ["best"]
        assert decision.confidence == 0.95

    @pytest.mark.asyncio
    async def test_llm_route_fallback_on_llm_exception(self):
        """If LLM call raises, fallback to highest confidence agent."""
        llm = Mock(spec=LLMProvider)
        llm.complete = Mock(side_effect=RuntimeError("LLM down"))
        orch = AgentOrchestrator(llm=llm)

        capable = [
            ("fallback", CapabilityResponse(agent_name="fallback", level=CapabilityLevel.CAN_HANDLE, confidence=0.8, reasoning="Here")),
        ]

        decision = await orch._llm_route({}, "test", capable)

        assert decision.selected_agents == ["fallback"]

    @pytest.mark.asyncio
    async def test_llm_route_empty_selected_falls_back(self):
        """If LLM returns empty selected list, fallback to highest confidence."""
        llm = Mock(spec=LLMProvider)
        llm.complete = Mock(
            return_value=Mock(
                content='{"selected": [], "parallel": false, "reasoning": "none"}'
            )
        )
        orch = AgentOrchestrator(llm=llm)

        capable = [
            ("only", CapabilityResponse(agent_name="only", level=CapabilityLevel.CAN_HANDLE, confidence=0.85, reasoning="Me")),
        ]

        decision = await orch._llm_route({}, "test", capable)

        # Empty selected falls through to the fallback path
        assert decision.selected_agents == ["only"]


# ===================================================================
# Capability Checking
# ===================================================================


class TestCheckAllCapabilities:
    """Test parallel capability checking across agents."""

    @pytest.mark.asyncio
    async def test_all_agents_checked(self):
        """Every registered agent should be checked for capability."""
        orch = _make_orchestrator_with_agents(a={}, b={}, c={})
        caps = await orch._check_all_capabilities({"task": "test"})

        assert set(caps.keys()) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_exception_in_capability_check_returns_cannot_handle(self):
        """If an agent's can_handle raises, it should be marked CANNOT_HANDLE."""
        llm = Mock(spec=LLMProvider)
        orch = AgentOrchestrator(llm=llm)

        runner = _make_mock_runner(name="broken")
        runner.can_handle = AsyncMock(side_effect=RuntimeError("broken"))
        orch.register_runner("broken", runner)

        caps = await orch._check_all_capabilities({"task": "test"})

        assert caps["broken"].level == CapabilityLevel.CANNOT_HANDLE
        assert caps["broken"].confidence == 0.0
        assert "Error" in caps["broken"].reasoning


# ===================================================================
# Message Log
# ===================================================================


class TestMessageLog:
    """Test message logging and retrieval."""

    def test_empty_log_on_init(self):
        """New orchestrator should have an empty message log."""
        orch = AgentOrchestrator(llm=Mock(spec=LLMProvider))
        assert orch.get_message_log() == []

    @pytest.mark.asyncio
    async def test_dispatch_populates_log(self):
        """Dispatching a request should add messages to the log."""
        orch = _make_orchestrator_with_agents(sales={})
        await orch.dispatch({"task": "sell"})

        log = orch.get_message_log()
        assert len(log) > 0

    def test_clear_message_log(self):
        """clear_message_log should empty the log."""
        orch = AgentOrchestrator(llm=Mock(spec=LLMProvider))
        orch._message_log.append(
            AgentMessage(type=MessageType.REQUEST, content={"x": 1})
        )
        assert len(orch.get_message_log()) == 1

        orch.clear_message_log()
        assert orch.get_message_log() == []

    def test_get_message_log_returns_copy(self):
        """get_message_log should return a copy, not the internal list."""
        orch = AgentOrchestrator(llm=Mock(spec=LLMProvider))
        log = orch.get_message_log()
        log.append("should not affect internal")

        assert len(orch.get_message_log()) == 0


# ===================================================================
# Cleanup
# ===================================================================


class TestCleanup:
    """Test resource cleanup."""

    def test_cleanup_calls_runner_cleanup(self):
        """cleanup should call cleanup() on every registered runner."""
        orch = _make_orchestrator_with_agents(a={}, b={})
        runners = {name: agent.runner for name, agent in orch._agents.items()}

        orch.cleanup()

        for runner in runners.values():
            runner.cleanup.assert_called_once()

    def test_cleanup_clears_registry(self):
        """cleanup should remove all agents from the registry."""
        orch = _make_orchestrator_with_agents(a={}, b={})
        orch.cleanup()

        assert len(orch._agents) == 0
        assert orch.list_agents() == []
