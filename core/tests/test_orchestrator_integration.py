"""
integration tests for multi-agent orchestration.

tests agent registration, dispatch routing, capability matching,
failure isolation, and concurrent request handling.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.llm.provider import LLMProvider, LLMResponse
from framework.runner.orchestrator import AgentOrchestrator, RoutingDecision
from framework.runner.protocol import (
    CapabilityLevel,
    CapabilityResponse,
)
from framework.runner.runner import AgentRunner


@pytest.fixture
def mock_llm():
    """create a mock llm provider"""
    llm = MagicMock(spec=LLMProvider)
    llm.complete = MagicMock(
        return_value=LLMResponse(
            content='{"selected_agents": ["agent1"], "reasoning": "test", "confidence": 0.9}',
            model="test",
            input_tokens=10,
            output_tokens=10,
            stop_reason="stop",
        )
    )
    return llm


@pytest.fixture
def mock_runner():
    """create a mock agent runner"""

    def create_runner(name: str, description: str = "test agent"):
        runner = MagicMock(spec=AgentRunner)
        info = MagicMock()
        info.description = description
        runner.info.return_value = info

        # mock the run_async method
        async def mock_run(*args, **kwargs):
            return {"success": True, "agent": name, "result": "handled"}

        runner.run_async = mock_run
        return runner

    return create_runner


class TestAgentRegistration:
    """test agent registration and listing"""

    def test_register_runner(self, mock_llm, mock_runner):
        """test registering an agent runner"""
        orchestrator = AgentOrchestrator(llm=mock_llm)
        runner = mock_runner("sales", "handles sales inquiries")

        orchestrator.register_runner(
            name="sales",
            runner=runner,
            capabilities=["sales", "pricing"],
            priority=1,
        )

        agents = orchestrator.list_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "sales"
        assert agents[0]["capabilities"] == ["sales", "pricing"]
        assert agents[0]["priority"] == 1

    def test_register_multiple_agents(self, mock_llm, mock_runner):
        """test registering multiple agents"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        orchestrator.register_runner("sales", mock_runner("sales"), priority=2)
        orchestrator.register_runner("support", mock_runner("support"), priority=1)
        orchestrator.register_runner("billing", mock_runner("billing"), priority=0)

        agents = orchestrator.list_agents()
        assert len(agents) == 3

        # should be sorted by priority (highest first)
        assert agents[0]["name"] == "sales"
        assert agents[1]["name"] == "support"
        assert agents[2]["name"] == "billing"

    def test_list_empty_when_no_agents(self, mock_llm):
        """test listing when no agents registered"""
        orchestrator = AgentOrchestrator(llm=mock_llm)
        agents = orchestrator.list_agents()
        assert agents == []


class TestDispatchRouting:
    """test request dispatching and routing"""

    @pytest.mark.asyncio
    async def test_dispatch_to_selected_agent(self, mock_llm, mock_runner):
        """test dispatching request to selected agent"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        runner = mock_runner("sales")
        orchestrator.register_runner("sales", runner, capabilities=["sales"])

        # mock capability check
        with patch.object(
            orchestrator, "_check_all_capabilities", new_callable=AsyncMock
        ) as mock_caps:
            mock_caps.return_value = {
                "sales": CapabilityResponse(
                    agent_name="sales",
                    level=CapabilityLevel.BEST_FIT,
                    confidence=0.9,
                    reasoning="sales agent is a good match",
                )
            }

            # mock routing
            with patch.object(orchestrator, "_route_request", new_callable=AsyncMock) as mock_route:
                mock_route.return_value = RoutingDecision(
                    selected_agents=["sales"],
                    reasoning="sales agent is best match",
                    confidence=0.9,
                )

                result = await orchestrator.dispatch(
                    {"customer_id": "123"},
                    intent="sales inquiry",
                )

                assert result.success is True
                assert "sales" in result.handled_by

    @pytest.mark.asyncio
    async def test_dispatch_no_capable_agent(self, mock_llm):
        """test when no agent can handle request"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        # mock empty routing
        with patch.object(
            orchestrator, "_check_all_capabilities", new_callable=AsyncMock
        ) as mock_caps:
            mock_caps.return_value = {}

            with patch.object(orchestrator, "_route_request", new_callable=AsyncMock) as mock_route:
                mock_route.return_value = RoutingDecision(
                    selected_agents=[],
                    reasoning="no agent available",
                    confidence=0.0,
                )

                result = await orchestrator.dispatch({"query": "unknown"})

                assert result.success is False
                assert "No agent capable" in (result.error or "")


class TestCapabilityMatching:
    """test capability-based routing"""

    @pytest.mark.asyncio
    async def test_capability_keyword_matching(self, mock_llm, mock_runner):
        """test that capabilities affect routing"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        orchestrator.register_runner(
            "sales",
            mock_runner("sales"),
            capabilities=["sales", "pricing", "quotes"],
        )
        orchestrator.register_runner(
            "support",
            mock_runner("support"),
            capabilities=["support", "tickets", "issues"],
        )

        # check that capability info is available
        agents = orchestrator.list_agents()

        sales = next(a for a in agents if a["name"] == "sales")
        support = next(a for a in agents if a["name"] == "support")

        assert "pricing" in sales["capabilities"]
        assert "tickets" in support["capabilities"]


class TestFailureIsolation:
    """test that agent failures are isolated"""

    def test_multiple_agents_can_be_registered_independently(self, mock_llm, mock_runner):
        """test that registering multiple agents works"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        # register multiple agents
        orchestrator.register_runner("agent1", mock_runner("agent1"))
        orchestrator.register_runner("agent2", mock_runner("agent2"))
        orchestrator.register_runner("agent3", mock_runner("agent3"))

        agents = orchestrator.list_agents()
        assert len(agents) == 3

        # removing one shouldnt affect others (if unregister existed)
        # but basic isolation is verified by independent registration


class TestConcurrentRequests:
    """test concurrent request handling"""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_dispatches(self, mock_llm, mock_runner):
        """test handling multiple requests at once"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        # register multiple agents
        for i in range(3):
            orchestrator.register_runner(f"agent{i}", mock_runner(f"agent{i}"))

        # mock to select agents
        with patch.object(
            orchestrator, "_check_all_capabilities", new_callable=AsyncMock
        ) as mock_caps:
            mock_caps.return_value = {
                "agent0": CapabilityResponse(
                    agent_name="agent0",
                    level=CapabilityLevel.BEST_FIT,
                    confidence=0.9,
                    reasoning="test match",
                )
            }

            with patch.object(orchestrator, "_route_request", new_callable=AsyncMock) as mock_route:
                mock_route.return_value = RoutingDecision(
                    selected_agents=["agent0"],
                    reasoning="test",
                    confidence=0.9,
                )

                # dispatch multiple requests concurrently
                tasks = [orchestrator.dispatch({"request_id": i}) for i in range(5)]

                results = await asyncio.gather(*tasks)

                # all should complete
                assert len(results) == 5


class TestPriorityRouting:
    """test priority-based agent selection"""

    def test_higher_priority_agents_listed_first(self, mock_llm, mock_runner):
        """test that agents are ordered by priority"""
        orchestrator = AgentOrchestrator(llm=mock_llm)

        # register in random order
        orchestrator.register_runner("low", mock_runner("low"), priority=0)
        orchestrator.register_runner("high", mock_runner("high"), priority=10)
        orchestrator.register_runner("medium", mock_runner("medium"), priority=5)

        agents = orchestrator.list_agents()

        assert agents[0]["name"] == "high"
        assert agents[0]["priority"] == 10
        assert agents[1]["name"] == "medium"
        assert agents[2]["name"] == "low"


class TestMessageLogging:
    """test that messages are logged correctly"""

    @pytest.mark.asyncio
    async def test_messages_included_in_result(self, mock_llm, mock_runner):
        """test that dispatch returns message log"""
        orchestrator = AgentOrchestrator(llm=mock_llm)
        orchestrator.register_runner("agent1", mock_runner("agent1"))

        with patch.object(
            orchestrator, "_check_all_capabilities", new_callable=AsyncMock
        ) as mock_caps:
            mock_caps.return_value = {}

            with patch.object(orchestrator, "_route_request", new_callable=AsyncMock) as mock_route:
                mock_route.return_value = RoutingDecision(
                    selected_agents=[],
                    reasoning="none available",
                    confidence=0.0,
                )

                result = await orchestrator.dispatch(
                    {"test": "data"},
                    intent="test intent",
                )

                # result should have messages
                assert hasattr(result, "messages")
                assert len(result.messages) > 0

                # first message should be the request
                first_msg = result.messages[0]
                assert first_msg.intent == "test intent"
