"""
CLI command for starting the WebSocket streaming server.

Adds 'stream' subcommand to the framework CLI:
    python -m framework stream --host 0.0.0.0 --port 8765
"""

import argparse
import asyncio
import logging
import signal

from framework.runtime.event_bus import EventBus
from framework.runtime.websocket_server import WebSocketServer

logger = logging.getLogger(__name__)


def register_stream_command(subparsers):
    """Register the 'stream' command with the CLI."""
    stream_parser = subparsers.add_parser(
        "stream",
        help="Start WebSocket server for real-time agent execution streaming",
        description=(
            "Start a WebSocket server that streams EventBus events to connected clients. "
            "Enables real-time monitoring of agent execution, goal progress, and HITL workflows."
        ),
    )
    
    stream_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Server host (default: 0.0.0.0 for all interfaces)",
    )
    
    stream_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Server port (default: 8765)",
    )
    
    stream_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    
    stream_parser.set_defaults(func=cmd_stream)


def cmd_stream(args) -> int:
    """Execute the 'stream' command."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    logger.info("Initializing Hive Agent Streaming Server...")
    
    # Create event bus
    bus = EventBus()
    
    # Create WebSocket server
    server = WebSocketServer(
        event_bus=bus,
        host=args.host,
        port=args.port,
    )
    
    # Run server
    asyncio.run(_run_server(server, args))
    
    return 0


async def _run_server(server: WebSocketServer, args):
    """Run the WebSocket server with graceful shutdown."""
    # Start server
    await server.start()
    
    logger.info("=" * 60)
    logger.info("Hive Agent Streaming Server is running!")
    logger.info(f"   WebSocket URL: ws://{args.host}:{args.port}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Connect your client with:")
    logger.info('  wscat -c "ws://localhost:8765"')
    logger.info("")
    logger.info("Subscribe to events:")
    logger.info('  {"action": "subscribe"}')
    logger.info('  {"action": "subscribe", "stream_id": "webhook"}')
    logger.info('  {"action": "subscribe", "event_types": ["EXECUTION_STARTED", "GOAL_PROGRESS"]}')
    logger.info("")
    logger.info("Press Ctrl+C to stop the server")
    logger.info("=" * 60)
    
    # Setup graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    
    def signal_handler(sig, frame):
        logger.info(f"\nReceived signal {sig}, shutting down gracefully...")
        shutdown_event.set()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Wait for shutdown signal
    try:
        await shutdown_event.wait()
    finally:
        await server.stop()
        logger.info("Server stopped. Goodbye!")
