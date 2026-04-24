"""Message protocol for multi-agent communication."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class MessageType(Enum):
    """Types of messages in the system."""

    REQUEST = "request"  # Initial request from user/orchestrator
    RESPONSE = "response"  # Response to a request
    HANDOFF = "handoff"  # Agent passing work to another agent
    BROADCAST = "broadcast"  # Message to all agents
    CAPABILITY_CHECK = "capability_check"  # Asking if agent can handle
    CAPABILITY_RESPONSE = "capability_response"  # Agent's answer


class CapabilityLevel(Enum):
    """How confident an agent is about handling a request."""

    CANNOT_HANDLE = "cannot_handle"  # Definitely not for this agent
    UNCERTAIN = "uncertain"  # Might be able to help
    CAN_HANDLE = "can_handle"  # Yes, this is what I do
    BEST_FIT = "best_fit"  # This is exactly what I'm designed for


@dataclass
class AgentMessage:
    """
    A message in the multi-agent system.

    All communication between agents goes through messages.
    The orchestrator routes and logs all messages.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: MessageType = MessageType.REQUEST
    from_agent: str | None = None  # None if from user/orchestrator
    to_agent: str | None = None  # None if broadcast or routing
    intent: str = ""  # Human-readable description of what's being asked
    content: dict = field(default_factory=dict)  # The actual payload
    requires_response: bool = True
    parent_id: str | None = None  # For threading conversations
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def reply(
        self,
        from_agent: str,
        content: dict,
        type: MessageType = MessageType.RESPONSE,
    ) -> "AgentMessage":
        """Create a reply to this message."""
        return AgentMessage(
            type=type,
            from_agent=from_agent,
            to_agent=self.from_agent,
            intent=f"Reply to: {self.intent}",
            content=content,
            requires_response=False,
            parent_id=self.id,
        )


@dataclass
class CapabilityResponse:
    """An agent's response to a capability check."""

    agent_name: str
    level: CapabilityLevel
    confidence: float  # 0.0 to 1.0
    reasoning: str  # Why the agent thinks it can/cannot handle
    estimated_steps: int | None = None  # How many steps it would take
    dependencies: list[str] = field(default_factory=list)  # Other agents needed


@dataclass
class OrchestratorResult:
    """Result of orchestrator dispatching a request."""

    success: bool
    handled_by: list[str]  # Agent(s) that handled the request
    results: dict[str, Any]  # Results keyed by agent name
    messages: list[AgentMessage]  # Full message trace
    error: str | None = None


@dataclass
class RegisteredAgent:
    """An agent registered with the orchestrator."""

    name: str
    runner: Any  # AgentRunner - using Any to avoid circular import
    description: str
    capabilities: list[str]  # High-level capability keywords
    priority: int = 0  # Higher = checked first for routing
