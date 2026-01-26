"""
WebSocket Event Streaming - Real-time observability for agent execution.

Provides a WebSocket server that streams agent events to connected clients
for live monitoring, debugging, and building dashboards.

Usage:
    # Start the server
    from framework.runtime.websocket_server import WebSocketEventServer
    
    server = WebSocketEventServer(event_bus, host="localhost", port=8765)
    await server.start()
    
    # Connect with any WebSocket client
    # ws://localhost:8765
    
    # Filter events by type (send as JSON message):
    # {"action": "subscribe", "event_types": ["execution_started", "execution_completed"]}
    
    # Unsubscribe from specific types:
    # {"action": "unsubscribe", "event_types": ["state_changed"]}

Protocol:
    - Server sends events as JSON: {"type": "event", "payload": {...}}
    - Server sends heartbeats: {"type": "heartbeat", "timestamp": "..."}
    - Client sends subscriptions: {"action": "subscribe", "event_types": [...]}
    - Client sends pings: {"action": "ping"}
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

try:
    import websockets
    from websockets.server import WebSocketServerProtocol
    from websockets.exceptions import ConnectionClosed
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    WebSocketServerProtocol = Any

if TYPE_CHECKING:
    from framework.runtime.event_bus import EventBus, AgentEvent, EventType

logger = logging.getLogger(__name__)


@dataclass
class ConnectedClient:
    """Represents a connected WebSocket client."""
    id: str
    websocket: WebSocketServerProtocol
    connected_at: datetime = field(default_factory=datetime.now)
    subscribed_types: set[str] = field(default_factory=set)  # Empty = all types
    filter_stream: str | None = None
    filter_execution: str | None = None
    messages_sent: int = 0
    last_activity: datetime = field(default_factory=datetime.now)


class WebSocketEventServer:
    """
    WebSocket server for streaming agent events in real-time.
    
    Integrates with EventBus to broadcast events to all connected clients.
    Supports filtering by event type, stream, and execution ID.
    
    Example:
        from framework.runtime.event_bus import EventBus
        from framework.runtime.websocket_server import WebSocketEventServer
        
        event_bus = EventBus()
        server = WebSocketEventServer(event_bus, port=8765)
        
        # Start server (non-blocking)
        await server.start()
        
        # Events published to event_bus will be broadcast to all clients
        await event_bus.publish(event)
        
        # Stop server
        await server.stop()
    """
    
    def __init__(
        self,
        event_bus: "EventBus",
        host: str = "localhost",
        port: int = 8765,
        heartbeat_interval: float = 30.0,
        max_clients: int = 100,
    ):
        """
        Initialize the WebSocket server.
        
        Args:
            event_bus: EventBus to subscribe to for events
            host: Host to bind to
            port: Port to listen on
            heartbeat_interval: Seconds between heartbeat messages
            max_clients: Maximum concurrent client connections
        """
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError(
                "websockets package required for WebSocket server. "
                "Install with: pip install websockets"
            )
        
        self.event_bus = event_bus
        self.host = host
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.max_clients = max_clients
        
        self._clients: dict[str, ConnectedClient] = {}
        self._server = None
        self._heartbeat_task: asyncio.Task | None = None
        self._subscription_id: str | None = None
        self._client_counter = 0
        self._running = False
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """Start the WebSocket server."""
        if self._running:
            logger.warning("WebSocket server already running")
            return
        
        # Subscribe to all events from the event bus
        from framework.runtime.event_bus import EventType
        self._subscription_id = self.event_bus.subscribe(
            event_types=list(EventType),
            handler=self._broadcast_event,
        )
        
        # Start the WebSocket server
        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
        )
        
        self._running = True
        
        # Start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        logger.info(f"🔌 WebSocket server started on ws://{self.host}:{self.port}")
    
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel heartbeat task
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Unsubscribe from event bus
        if self._subscription_id:
            self.event_bus.unsubscribe(self._subscription_id)
        
        # Close all client connections
        async with self._lock:
            for client in list(self._clients.values()):
                try:
                    await client.websocket.close(1001, "Server shutting down")
                except Exception:
                    pass
            self._clients.clear()
        
        # Stop the server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        logger.info("🔌 WebSocket server stopped")
    
    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a new WebSocket client connection."""
        # Check max clients
        if len(self._clients) >= self.max_clients:
            await websocket.close(1013, "Maximum clients reached")
            return
        
        # Create client
        async with self._lock:
            self._client_counter += 1
            client_id = f"client_{self._client_counter}"
            client = ConnectedClient(id=client_id, websocket=websocket)
            self._clients[client_id] = client
        
        logger.info(f"📡 Client {client_id} connected from {websocket.remote_address}")
        
        # Send welcome message
        await self._send_to_client(client, {
            "type": "welcome",
            "client_id": client_id,
            "server_time": datetime.now().isoformat(),
            "available_event_types": self._get_event_types(),
        })
        
        try:
            async for message in websocket:
                await self._handle_message(client, message)
        except ConnectionClosed:
            logger.info(f"📡 Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            async with self._lock:
                self._clients.pop(client_id, None)
    
    async def _handle_message(self, client: ConnectedClient, message: str) -> None:
        """Handle a message from a client."""
        try:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "ping":
                await self._send_to_client(client, {
                    "type": "pong",
                    "timestamp": datetime.now().isoformat(),
                })
            
            elif action == "subscribe":
                event_types = data.get("event_types", [])
                if event_types:
                    client.subscribed_types.update(event_types)
                else:
                    client.subscribed_types.clear()  # Subscribe to all
                
                client.filter_stream = data.get("filter_stream")
                client.filter_execution = data.get("filter_execution")
                
                await self._send_to_client(client, {
                    "type": "subscribed",
                    "event_types": list(client.subscribed_types) if client.subscribed_types else "all",
                    "filter_stream": client.filter_stream,
                    "filter_execution": client.filter_execution,
                })
            
            elif action == "unsubscribe":
                event_types = data.get("event_types", [])
                for et in event_types:
                    client.subscribed_types.discard(et)
                
                await self._send_to_client(client, {
                    "type": "unsubscribed",
                    "event_types": event_types,
                })
            
            elif action == "get_stats":
                await self._send_to_client(client, {
                    "type": "stats",
                    "connected_clients": len(self._clients),
                    "your_messages_sent": client.messages_sent,
                    "your_connected_at": client.connected_at.isoformat(),
                })
            
            else:
                await self._send_to_client(client, {
                    "type": "error",
                    "message": f"Unknown action: {action}",
                })
            
            client.last_activity = datetime.now()
            
        except json.JSONDecodeError:
            await self._send_to_client(client, {
                "type": "error",
                "message": "Invalid JSON",
            })
    
    async def _broadcast_event(self, event: "AgentEvent") -> None:
        """Broadcast an event to all subscribed clients."""
        if not self._running:
            return
        
        event_dict = event.to_dict()
        message = {
            "type": "event",
            "payload": event_dict,
        }
        
        async with self._lock:
            clients_to_notify = list(self._clients.values())
        
        for client in clients_to_notify:
            # Check if client is subscribed to this event type
            if client.subscribed_types and event.type.value not in client.subscribed_types:
                continue
            
            # Check stream filter
            if client.filter_stream and event.stream_id != client.filter_stream:
                continue
            
            # Check execution filter
            if client.filter_execution and event.execution_id != client.filter_execution:
                continue
            
            await self._send_to_client(client, message)
    
    async def _send_to_client(self, client: ConnectedClient, message: dict) -> bool:
        """Send a message to a specific client."""
        try:
            await client.websocket.send(json.dumps(message))
            client.messages_sent += 1
            return True
        except ConnectionClosed:
            return False
        except Exception as e:
            logger.error(f"Error sending to client {client.id}: {e}")
            return False
    
    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to all clients."""
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                message = {
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat(),
                    "connected_clients": len(self._clients),
                }
                
                async with self._lock:
                    clients = list(self._clients.values())
                
                for client in clients:
                    await self._send_to_client(client, message)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    def _get_event_types(self) -> list[str]:
        """Get list of available event types."""
        from framework.runtime.event_bus import EventType
        return [et.value for et in EventType]
    
    @property
    def client_count(self) -> int:
        """Get current number of connected clients."""
        return len(self._clients)
    
    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running


async def create_websocket_server(
    event_bus: "EventBus",
    host: str = "localhost",
    port: int = 8765,
) -> WebSocketEventServer:
    """
    Create and start a WebSocket event server.
    
    Convenience function for quick setup.
    
    Args:
        event_bus: EventBus to stream events from
        host: Host to bind to
        port: Port to listen on
        
    Returns:
        Started WebSocketEventServer instance
    """
    server = WebSocketEventServer(event_bus, host=host, port=port)
    await server.start()
    return server
