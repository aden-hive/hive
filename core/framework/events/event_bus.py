"""Event bus for event-driven architecture."""

from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
from enum import Enum
import uuid
import asyncio
from pydantic import BaseModel


class EventType(str, Enum):
    """Standard event types."""
    AGENT_CREATED = "agent.created"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    NODE_EXECUTED = "node.executed"
    NODE_FAILED = "node.failed"
    TOOL_INVOKED = "tool.invoked"
    LLM_REQUEST_SENT = "llm.request_sent"
    LLM_RESPONSE_RECEIVED = "llm.response_received"
    DECISION_MADE = "decision.made"
    USER_INTERACTION = "user.interaction"
    CONFIG_CHANGED = "config.changed"
    FEATURE_FLAG_TOGGLED = "feature_flag.toggled"


class Event(BaseModel):
    """Base event model."""
    id: str = None
    type: str
    source: str
    data: Dict[str, Any]
    metadata: Dict[str, Any] = {}
    timestamp: datetime = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

    def __init__(self, **data):
        if 'id' not in data:
            data['id'] = str(uuid.uuid4())
        if 'timestamp' not in data:
            data['timestamp'] = datetime.utcnow()
        super().__init__(**data)


class EventBus:
    """Event bus for publishing and subscribing to events."""

    def __init__(self, backend: str = "memory"):
        self.backend = backend
        self._subscribers: Dict[str, List[Callable]] = {}
        self._middleware: List[Callable] = []
        self._event_store: List[Event] = []

    async def publish(self, event: Event) -> None:
        """Publish an event to the bus."""
        # Apply middleware
        processed_event = event
        for mw in self._middleware:
            processed_event = await mw(processed_event)

        # Store in event store
        self._event_store.append(processed_event)

        # Notify local subscribers
        if event.type in self._subscribers:
            tasks = [
                handler(processed_event)
                for handler in self._subscribers[event.type]
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)

    def add_middleware(self, middleware: Callable) -> None:
        """Add event processing middleware."""
        self._middleware.append(middleware)

    async def get_events(
        self,
        event_type: str = None,
        limit: int = 100
    ) -> List[Event]:
        """Get events from store."""
        events = self._event_store
        if event_type:
            events = [e for e in events if e.type == event_type]
        return sorted(events, key=lambda x: x.timestamp, reverse=True)[:limit]

    async def replay_events(
        self,
        handler: Callable,
        event_type: str = None
    ) -> None:
        """Replay events from store."""
        events = await self.get_events(event_type)
        for event in events:
            await handler(event)
