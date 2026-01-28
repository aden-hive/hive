"""
Audit Logging - Persist agent execution events to disk.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import aiofiles

from framework.runtime.event_bus import AgentEvent, EventBus

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Logs all events from the EventBus to a daily JSONL file.

    Usage:
        bus = EventBus()
        audit = AuditLogger(bus, log_dir="logs")
        await audit.start()
        ...
        await audit.stop()
    """

    def __init__(self, event_bus: EventBus, log_dir: str = "logs"):
        self.event_bus = event_bus
        self.log_dir = Path(log_dir)
        self.subscription_id: str | None = None
        self._ensure_log_dir()

    def _ensure_log_dir(self) -> None:
        """Create log directory if it doesn't exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_file(self) -> Path:
        """Get the current daily log file path."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"audit_{date_str}.jsonl"

    async def start(self) -> None:
        """Start listening to events."""
        if self.subscription_id:
            return

        # Subscribe to ALL events
        # We need to list all event types or handle the subscription carefully.
        # The EventBus subscribe method takes a list of EventTypes.
        # We'll import EventType to get all of them.
        from framework.runtime.event_bus import EventType

        all_types = list(EventType)

        self.subscription_id = self.event_bus.subscribe(
            event_types=all_types, handler=self._handle_event
        )
        logger.info(f"Audit logger started, writing to {self._get_log_file()}")

    async def stop(self) -> None:
        """Stop listening to events."""
        if self.subscription_id:
            self.event_bus.unsubscribe(self.subscription_id)
            self.subscription_id = None
            logger.info("Audit logger stopped")

    async def _handle_event(self, event: AgentEvent) -> None:
        """Write event to the log file."""
        try:
            log_file = self._get_log_file()
            event_dict = event.to_dict()

            # Use append mode
            async with aiofiles.open(log_file, mode="a") as f:
                await f.write(json.dumps(event_dict) + "\n")

        except Exception as e:
            # Don't let audit logging crash the agent, but log the error
            logger.error(f"Failed to write audit log: {e}")
