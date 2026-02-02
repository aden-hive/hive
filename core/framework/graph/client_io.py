"""
Client I/O gateway for graph nodes.

Provides the bridge between node code and external clients:
- ActiveNodeClientIO: for client_facing=True nodes (streams output, accepts input)
- InertNodeClientIO: for client_facing=False nodes (logs internally, redirects input)
- ClientIOGateway: factory that creates the right variant per node
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)


class NodeClientIO(ABC):
    """Abstract base for node client I/O."""

    @abstractmethod
    async def emit_output(self, content: str, is_final: bool = False) -> None:
        """Emit output content. If is_final=True, signal end of stream."""

    @abstractmethod
    async def request_input(self, prompt: str = "", timeout: float | None = None) -> str:
        """Request input. Behavior depends on whether the node is client-facing."""


class ActiveNodeClientIO(NodeClientIO):
    """
    Client I/O for client_facing=True nodes.

    - emit_output() queues content and publishes CLIENT_OUTPUT_DELTA.
    - request_input() publishes CLIENT_INPUT_REQUESTED, then awaits provide_input().
    - output_stream() yields queued content until the final sentinel.
    """

    def __init__(
        self,
        node_id: str,
        event_bus: EventBus | None = None,
    ) -> None:
        self.node_id = node_id
        self._event_bus = event_bus

        self._output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._output_snapshot = ""

        self._input_event: asyncio.Event | None = None
        self._input_result: str | None = None

    async def emit_output(self, content: str, is_final: bool = False) -> None:
        self._output_snapshot += content
        await self._output_queue.put(content)

        if self._event_bus is not None:
            await self._event_bus.emit_client_output_delta(
                stream_id=self.node_id,
                node_id=self.node_id,
                content=content,
                snapshot=self._output_snapshot,
            )

        if is_final:
            await self._output_queue.put(None)

    async def request_input(self, prompt: str = "", timeout: float | None = None) -> str:
        if self._input_event is not None:
            raise RuntimeError("request_input already pending for this node")

        self._input_event = asyncio.Event()
        self._input_result = None

        if self._event_bus is not None:
            await self._event_bus.emit_client_input_requested(
                stream_id=self.node_id,
                node_id=self.node_id,
                prompt=prompt,
            )

        try:
            if timeout is not None:
                await asyncio.wait_for(self._input_event.wait(), timeout=timeout)
            else:
                await self._input_event.wait()
        finally:
            self._input_event = None

        if self._input_result is None:
            raise RuntimeError("input event was set but no input was provided")
        result = self._input_result
        self._input_result = None
        return result

    async def provide_input(self, content: str) -> None:
        """Called externally to fulfill a pending request_input()."""
        if self._input_event is None:
            raise RuntimeError("no pending request_input to fulfill")
        self._input_result = content
        self._input_event.set()

    async def output_stream(self) -> AsyncIterator[str]:
        """Async iterator that yields output chunks until the final sentinel."""
        while True:
            chunk = await self._output_queue.get()
            if chunk is None:
                break
            yield chunk


class InertNodeClientIO(NodeClientIO):
    """
    Client I/O for client_facing=False nodes.

    - emit_output() publishes NODE_INTERNAL_OUTPUT (content is not discarded).
    - request_input() publishes NODE_INPUT_BLOCKED and returns a redirect string.
    """

    def __init__(
        self,
        node_id: str,
        event_bus: EventBus | None = None,
    ) -> None:
        self.node_id = node_id
        self._event_bus = event_bus

    async def emit_output(self, content: str, is_final: bool = False) -> None:
        if self._event_bus is not None:
            await self._event_bus.emit_node_internal_output(
                stream_id=self.node_id,
                node_id=self.node_id,
                content=content,
            )

    async def request_input(self, prompt: str = "", timeout: float | None = None) -> str:
        if self._event_bus is not None:
            await self._event_bus.emit_node_input_blocked(
                stream_id=self.node_id,
                node_id=self.node_id,
                prompt=prompt,
            )
        return "You are an internal processing node. There is no user to interact with. Work with the data provided in your inputs to complete your task."


class ClientIOGateway:
    """Factory that creates the appropriate NodeClientIO for a node."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus

    def create_io(self, node_id: str, client_facing: bool) -> NodeClientIO:
        if client_facing:
            return ActiveNodeClientIO(
                node_id=node_id,
                event_bus=self._event_bus,
            )
        return InertNodeClientIO(
            node_id=node_id,
            event_bus=self._event_bus,
        )
