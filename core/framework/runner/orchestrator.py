"""Agent Orchestrator - routes requests and relays messages between agents."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.llm.provider import LLMProvider
from framework.runner.protocol import (
    AgentMessage,
    CapabilityLevel,
    CapabilityResponse,
    MessageType,
    OrchestratorResult,
    RegisteredAgent,
)
from framework.runner.runner import AgentRunner


@dataclass
class RoutingDecision:
    """Decision about which agent(s) should handle a request."""

    selected_agents: list[str]
    reasoning: str
    confidence: float
    should_parallelize: bool = False
    fallback_agents: list[str] = field(default_factory=list)


class AgentOrchestrator:
    """
    Manages multiple agents and routes communications between them.

    The orchestrator:
    1. Maintains a registry of available agents
    2. Routes incoming requests to appropriate agent(s) using LLM
    3. Relays messages between agents
    4. Logs all communications for traceability

    Usage:
        orchestrator = AgentOrchestrator()
        orchestrator.register("sales", "exports/outbound-sales")
        orchestrator.register("support", "exports/customer-support")

        result = await orchestrator.dispatch({
            "intent": "help customer with billing issue",
            "customer_id": "123",
        })
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
        """
        Initialize the orchestrator.

        Args:
            llm: LLM provider for routing decisions (auto-creates if None)
            model: Model to use for routing
        """
        self._agents: dict[str, RegisteredAgent] = {}
        self._llm = llm
        self._model = model
        self._message_log: list[AgentMessage] = []

        # Auto-create LLM - LiteLLM auto-detects provider and API key from model name
        if self._llm is None:
            from framework.llm.litellm import LiteLLMProvider
            self._llm = LiteLLMProvider(model=self._model)

    def register(
        self,
        name: str,
        agent_path: str | Path,
        capabilities: list[str] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Register an agent with the orchestrator.

        Args:
            name: Unique name for this agent
            agent_path: Path to agent folder (containing agent.json)
            capabilities: Optional list of capability keywords
            priority: Higher = checked first for routing
        """
        runner = AgentRunner.load(agent_path)
        info = runner.info()

        self._agents[name] = RegisteredAgent(
            name=name,
            runner=runner,
            description=info.description,
            capabilities=capabilities or [],
            priority=priority,
        )

    def register_runner(
        self,
        name: str,
        runner: AgentRunner,
        capabilities: list[str] | None = None,
        priority: int = 0,
    ) -> None:
        """
        Register an existing AgentRunner.

        Args:
            name: Unique name for this agent
            runner: AgentRunner instance
            capabilities: Optional list of capability keywords
            priority: Higher = checked first for routing
        """
        info = runner.info()

        self._agents[name] = RegisteredAgent(
            name=name,
            runner=runner,
            description=info.description,
            capabilities=capabilities or [],
            priority=priority,
        )

    def list_agents(self) -> list[dict]:
        """List all registered agents."""
        return [
            {
                "name": agent.name,
                "description": agent.description,
                "capabilities": agent.capabilities,
                "priority": agent.priority,
            }
            for agent in sorted(
                self._agents.values(),
                key=lambda a: -a.priority,
            )
        ]

    async def dispatch(
        self,
        request: dict,
        intent: str | None = None,
    ) -> OrchestratorResult:
        """
        Route a request to the appropriate agent(s).

        Args:
            request: The request data
            intent: Optional description of what's being asked

        Returns:
            OrchestratorResult with results from handling agent(s)
        """
        messages: list[AgentMessage] = []

        # Create initial message
        initial_message = AgentMessage(
            type=MessageType.REQUEST,
            intent=intent or "Process request",
            content=request,
        )
        messages.append(initial_message)
        self._message_log.append(initial_message)

        # Step 1: Check capabilities of all agents
        capabilities = await self._check_all_capabilities(request)

        # Step 2: Route to best agent(s)
        routing = await self._route_request(request, intent, capabilities)

        if not routing.selected_agents:
            return OrchestratorResult(
                success=False,
                handled_by=[],
                results={},
                messages=messages,
                error="No agent capable of handling this request",
            )

        # Step 3: Execute on selected agent(s)
        results: dict[str, Any] = {}
        handled_by: list[str] = []

        if routing.should_parallelize and len(routing.selected_agents) > 1:
            # Run agents in parallel
            tasks = []
            for agent_name in routing.selected_agents:
                msg = AgentMessage(
                    type=MessageType.REQUEST,
                    from_agent="orchestrator",
                    to_agent=agent_name,
                    intent=intent or "Process request",
                    content=request,
                    parent_id=initial_message.id,
                )
                messages.append(msg)
                self._message_log.append(msg)
                tasks.append(self._send_to_agent(agent_name, msg))

            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for agent_name, response in zip(routing.selected_agents, responses):
                if isinstance(response, Exception):
                    results[agent_name] = {"error": str(response)}
                else:
                    messages.append(response)
                    self._message_log.append(response)
                    results[agent_name] = response.content
                    handled_by.append(agent_name)
        else:
            # Run agents sequentially
            accumulated_context = dict(request)

            for agent_name in routing.selected_agents:
                msg = AgentMessage(
                    type=MessageType.REQUEST,
                    from_agent="orchestrator",
                    to_agent=agent_name,
                    intent=intent or "Process request",
                    content=accumulated_context,
                    parent_id=initial_message.id,
                )
                messages.append(msg)
                self._message_log.append(msg)

                try:
                    response = await self._send_to_agent(agent_name, msg)
                    messages.append(response)
                    self._message_log.append(response)
                    results[agent_name] = response.content
                    handled_by.append(agent_name)

                    # Pass results to next agent
                    if "results" in response.content:
                        accumulated_context.update(response.content["results"])
                except Exception as e:
                    results[agent_name] = {"error": str(e)}
                    # Try fallback if available
                    if routing.fallback_agents:
                        fallback = routing.fallback_agents.pop(0)
                        routing.selected_agents.append(fallback)

        return OrchestratorResult(
            success=len(handled_by) > 0,
            handled_by=handled_by,
            results=results,
            messages=messages,
        )

    async def relay(
        self,
        from_agent: str,
        to_agent: str,
        content: dict,
        intent: str = "",
    ) -> AgentMessage:
        """
        Relay a message from one agent to another.

        Args:
            from_agent: Source agent name
            to_agent: Target agent name
            content: Message content
            intent: Description of what's being asked

        Returns:
            Response message from target agent
        """
        if to_agent not in self._agents:
            raise ValueError(f"Unknown agent: {to_agent}")

        message = AgentMessage(
            type=MessageType.HANDOFF,
            from_agent=from_agent,
            to_agent=to_agent,
            intent=intent,
            content=content,
        )
        self._message_log.append(message)

        response = await self._send_to_agent(to_agent, message)
        self._message_log.append(response)

        return response

    async def broadcast(
        self,
        content: dict,
        intent: str = "",
        exclude: list[str] | None = None,
    ) -> dict[str, AgentMessage]:
        """
        Send a message to all agents.

        Args:
            content: Message content
            intent: Description of what's being asked
            exclude: Agent names to exclude

        Returns:
            Dict of agent name -> response message
        """
        exclude = exclude or []
        responses: dict[str, AgentMessage] = {}

        message = AgentMessage(
            type=MessageType.BROADCAST,
            from_agent="orchestrator",
            intent=intent,
            content=content,
        )
        self._message_log.append(message)

        tasks = []
        agent_names = []
        for name in self._agents:
            if name not in exclude:
                agent_names.append(name)
                tasks.append(self._send_to_agent(name, message))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                responses[name] = AgentMessage(
                    type=MessageType.RESPONSE,
                    from_agent=name,
                    content={"error": str(result)},
                    parent_id=message.id,
                )
            else:
                responses[name] = result
                self._message_log.append(result)

        return responses

    async def _check_all_capabilities(
        self,
        request: dict,
    ) -> dict[str, CapabilityResponse]:
        """Check all agents' capabilities in parallel."""
        tasks = []
        agent_names = []

        for name, agent in self._agents.items():
            agent_names.append(name)
            tasks.append(agent.runner.can_handle(request, self._llm))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        capabilities = {}
        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                capabilities[name] = CapabilityResponse(
                    agent_name=name,
                    level=CapabilityLevel.CANNOT_HANDLE,
                    confidence=0.0,
                    reasoning=f"Error: {result}",
                )
            else:
                capabilities[name] = result

        return capabilities

    async def _route_request(
        self,
        request: dict,
        intent: str | None,
        capabilities: dict[str, CapabilityResponse],
    ) -> RoutingDecision:
        """Decide which agent(s) should handle the request."""

        # Filter to capable agents
        capable = [
            (name, cap)
            for name, cap in capabilities.items()
            if cap.level in (CapabilityLevel.BEST_FIT, CapabilityLevel.CAN_HANDLE)
        ]

        # Sort by confidence (highest first)
        capable.sort(key=lambda x: -x[1].confidence)

        # If only one capable agent, use it
        if len(capable) == 1:
            return RoutingDecision(
                selected_agents=[capable[0][0]],
                reasoning=capable[0][1].reasoning,
                confidence=capable[0][1].confidence,
            )

        # If multiple capable agents and we have LLM, let it decide
        if len(capable) > 1 and self._llm:
            return await self._llm_route(request, intent, capable)

        # If no capable agents, check uncertain ones
        uncertain = [
            (name, cap)
            for name, cap in capabilities.items()
            if cap.level == CapabilityLevel.UNCERTAIN
        ]
        if uncertain:
            uncertain.sort(key=lambda x: -x[1].confidence)
            return RoutingDecision(
                selected_agents=[uncertain[0][0]],
                reasoning=f"Uncertain match: {uncertain[0][1].reasoning}",
                confidence=uncertain[0][1].confidence,
                fallback_agents=[u[0] for u in uncertain[1:3]],
            )

        # No agents can handle
        return RoutingDecision(
            selected_agents=[],
            reasoning="No capable agents found",
            confidence=0.0,
        )

    async def _llm_route(
        self,
        request: dict,
        intent: str | None,
        capable: list[tuple[str, CapabilityResponse]],
    ) -> RoutingDecision:
        """Use LLM to decide routing when multiple agents are capable."""

        agents_info = "\n".join(
            f"- {name}: {cap.reasoning} (confidence: {cap.confidence:.2f})"
            for name, cap in capable
        )

        prompt = f"""Multiple agents can handle this request. Decide the best routing.

Request:
{json.dumps(request, indent=2)}

Intent: {intent or "Not specified"}

Capable agents:
{agents_info}

Decide:
1. Which agent(s) should handle this?
2. Should they run in parallel or sequence?
3. Why this routing?

Respond with JSON only:
{{
    "selected": ["agent_name", ...],
    "parallel": true/false,
    "reasoning": "explanation"
}}"""

        try:
            response = self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system="You are a request router. Respond with JSON only.",
                max_tokens=256,
            )

            import re
            json_match = re.search(r'\{[^{}]*\}', response.content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                selected = data.get("selected", [])
                # Validate selected agents exist
                selected = [s for s in selected if s in self._agents]
                if selected:
                    return RoutingDecision(
                        selected_agents=selected,
                        reasoning=data.get("reasoning", ""),
                        confidence=0.8,
                        should_parallelize=data.get("parallel", False),
                    )
        except Exception:
            pass

        # Fallback: use highest confidence
        return RoutingDecision(
            selected_agents=[capable[0][0]],
            reasoning=capable[0][1].reasoning,
            confidence=capable[0][1].confidence,
        )

    async def _send_to_agent(
        self,
        agent_name: str,
        message: AgentMessage,
    ) -> AgentMessage:
        """Send a message to an agent and get response."""
        agent = self._agents[agent_name]
        return await agent.runner.receive_message(message)

    def get_message_log(self) -> list[AgentMessage]:
        """Get full message log for debugging/tracing."""
        return list(self._message_log)

    def clear_message_log(self) -> None:
        """Clear the message log."""
        self._message_log.clear()

    def cleanup(self) -> None:
        """Clean up all agent resources."""
        for agent in self._agents.values():
            agent.runner.cleanup()
        self._agents.clear()
