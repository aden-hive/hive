"""
WebSocket Server for Real-Time Agent Execution Streaming.

Bridges EventBus events to WebSocket clients, enabling:
- Live monitoring of agent execution
- Real-time goal progress tracking
- Human-in-the-loop interventions
- Multi-stream observability

Usage:
    from framework.runtime.websocket_server import WebSocketServer
    from framework.runtime.event_bus import EventBus

    bus = EventBus()
    server = WebSocketServer(event_bus=bus, host="0.0.0.0", port=8765)
    await server.start()
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.server import serve, WebSocketServerProtocol

from framework.runtime.event_bus import AgentEvent, EventBus, EventType

logger = logging.getLogger(__name__)


@dataclass
class ClientFilter:
    """Filters for client subscriptions."""
    stream_id: str | None = None
    execution_id: str | None = None
    event_types: list[EventType] | None = None


class WebSocketServer:
    """
    WebSocket server that streams EventBus events to connected clients.

    Features:
    - Per-client filtering (stream_id, execution_id, event_types)
    - JSON message protocol
    - Automatic reconnection support
    - Connection lifecycle management

    Message Protocol:
        Client → Server (subscribe):
        {
            "action": "subscribe",
            "stream_id": "webhook",        # optional
            "execution_id": "exec_123",    # optional
            "event_types": ["EXECUTION_STARTED", "GOAL_PROGRESS"]  # optional
        }

        Server → Client (events):
        {
            "type": "event",
            "event": {
                "type": "EXECUTION_STARTED",
                "stream_id": "webhook",
                "execution_id": "exec_123",
                "data": {...},
                "timestamp": "2026-01-26T12:00:00",
                "correlation_id": "corr_123"
            }
        }

        Server → Client (error):
        {
            "type": "error",
            "message": "Invalid event type filter"
        }
    """

    def __init__(
        self,
        event_bus: EventBus,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        """
        Initialize WebSocket server.

        Args:
            event_bus: EventBus instance to bridge events from
            host: Server host (default: 0.0.0.0 for all interfaces)
            port: Server port (default: 8765)
        """
        self.event_bus = event_bus
        self.host = host
        self.port = port
        self._clients: dict[WebSocketServerProtocol, ClientFilter] = {}
        self._server = None
        self._subscription_ids: dict[WebSocketServerProtocol, str] = {}

    async def start(self) -> None:
        """Start the WebSocket server."""
        logger.info(f"Starting WebSocket server on ws://{self.host}:{self.port}")
        self._server = await serve(self._handle_client, self.host, self.port)
        logger.info("WebSocket server ready for connections")

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""
        logger.info("Stopping WebSocket server...")
        
        # Close all client connections
        for ws in list(self._clients.keys()):
            await ws.close()
        
        # Stop the server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        logger.info("WebSocket server stopped")

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a client connection lifecycle."""
        client_id = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"Client connected: {client_id}")
        
        # Initialize client with no filters
        self._clients[websocket] = ClientFilter()
        
        try:
            # Send welcome message
            await websocket.send(json.dumps({
                "type": "connected",
                "message": "Connected to Hive Agent Streaming Server",
                "version": "1.0.0",
            }))
            
            # Handle incoming messages
            async for message in websocket:
                try:
                    await self._handle_message(websocket, message)
                except Exception as e:
                    logger.error(f"Error handling message from {client_id}: {e}")
                    await self._send_error(websocket, str(e))
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        finally:
            # Clean up
            if websocket in self._subscription_ids:
                # Unsubscribe from EventBus
                sub_id = self._subscription_ids[websocket]
                self.event_bus.unsubscribe(sub_id)
                del self._subscription_ids[websocket]
            
            if websocket in self._clients:
                del self._clients[websocket]

    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str) -> None:
        """Process a message from a client."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            await self._send_error(websocket, "Invalid JSON")
            return
        
        action = data.get("action")
        
        if action == "subscribe":
            await self._handle_subscribe(websocket, data)
        elif action == "unsubscribe":
            await self._handle_unsubscribe(websocket)
        elif action == "ping":
            await websocket.send(json.dumps({"type": "pong"}))
        else:
            await self._send_error(websocket, f"Unknown action: {action}")

    async def _handle_subscribe(self, websocket: WebSocketServerProtocol, data: dict) -> None:
        """Handle client subscription request."""
        # Extract filters
        stream_id = data.get("stream_id")
        execution_id = data.get("execution_id")
        event_type_names = data.get("event_types")
        
        # Parse event types
        event_types = None
        if event_type_names:
            try:
                event_types = [EventType(name) for name in event_type_names]
            except ValueError as e:
                await self._send_error(websocket, f"Invalid event type: {e}")
                return
        
        # Update client filter
        self._clients[websocket] = ClientFilter(
            stream_id=stream_id,
            execution_id=execution_id,
            event_types=event_types,
        )
        
        # Unsubscribe from previous subscription if any
        if websocket in self._subscription_ids:
            self.event_bus.unsubscribe(self._subscription_ids[websocket])
        
        # Subscribe to EventBus with client-specific handler
        async def event_handler(event: AgentEvent) -> None:
            await self._send_event(websocket, event)
        
        sub_id = self.event_bus.subscribe(
            event_types=event_types or list(EventType),
            handler=event_handler,
            filter_stream=stream_id,
            filter_execution=execution_id,
        )
        
        self._subscription_ids[websocket] = sub_id
        
        # Acknowledge subscription
        await websocket.send(json.dumps({
            "type": "subscribed",
            "filters": {
                "stream_id": stream_id,
                "execution_id": execution_id,
                "event_types": event_type_names,
            }
        }))
        
        logger.info(f"Client subscribed with filters: stream={stream_id}, exec={execution_id}, types={event_type_names}")

    async def _handle_unsubscribe(self, websocket: WebSocketServerProtocol) -> None:
        """Handle client unsubscribe request."""
        if websocket in self._subscription_ids:
            sub_id = self._subscription_ids[websocket]
            self.event_bus.unsubscribe(sub_id)
            del self._subscription_ids[websocket]
            
        self._clients[websocket] = ClientFilter()
        
        await websocket.send(json.dumps({
            "type": "unsubscribed"
        }))

    async def _send_event(self, websocket: WebSocketServerProtocol, event: AgentEvent) -> None:
        """Send an event to a client."""
        try:
            await websocket.send(json.dumps({
                "type": "event",
                "event": event.to_dict(),
            }))
        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"Cannot send event, client disconnected")
        except Exception as e:
            logger.error(f"Error sending event to client: {e}")

    async def _send_error(self, websocket: WebSocketServerProtocol, message: str) -> None:
        """Send an error message to a client."""
        try:
            await websocket.send(json.dumps({
                "type": "error",
                "message": message,
            }))
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get server statistics."""
        return {
            "connected_clients": len(self._clients),
            "subscriptions": len(self._subscription_ids),
            "event_bus_stats": self.event_bus.get_stats(),
        }


async def main_example():
    """Example usage of WebSocket server."""
    # Create event bus
    bus = EventBus()
    
    # Create WebSocket server
    server = WebSocketServer(event_bus=bus, host="0.0.0.0", port=8765)
    
    # Start server
    await server.start()
    
    # Simulate some events (in real usage, these come from agent execution)
    async def emit_demo_events():
        await asyncio.sleep(2)
        
        # Execution started
        await bus.emit_execution_started(
            stream_id="demo_stream",
            execution_id="exec_001",
            input_data={"query": "test"},
        )
        
        await asyncio.sleep(1)
        
        # Goal progress
        await bus.emit_goal_progress(
            stream_id="demo_stream",
            progress=0.5,
            criteria_status={"criteria_1": "in_progress"},
        )
        
        await asyncio.sleep(1)
        
        # Execution completed
        await bus.emit_execution_completed(
            stream_id="demo_stream",
            execution_id="exec_001",
            output={"result": "success"},
        )
    
    # Start event emitter
    asyncio.create_task(emit_demo_events())
    
    # Keep server running
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        await server.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main_example())
