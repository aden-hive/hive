"""
Simple WebSocket client example for testing the streaming server.
"""

import asyncio
import json
import sys
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))



async def stream_client():
    """Connect to WebSocket server and stream events."""
    uri = "ws://localhost:8765"

    print(f"Connecting to {uri}...")

    async with websockets.connect(uri) as websocket:
        welcome = await websocket.recv()
        print(f"< {welcome}\n")

        subscribe_msg = {
            "action": "subscribe",
            # "stream_id": "demo_stream",  # Optional: filter by stream
            # "execution_id": "exec_001",   # Optional: filter by execution
            # "event_types": ["EXECUTION_STARTED", "GOAL_PROGRESS"],  # Optional: filter by types
        }

        print("> Subscribing with filters:")
        print(f"  {json.dumps(subscribe_msg, indent=2)}\n")
        await websocket.send(json.dumps(subscribe_msg))

        response = await websocket.recv()
        print(f"< {response}\n")

        print("Listening for events... (Ctrl+C to stop)\n")
        print("=" * 60)

        try:
            async for message in websocket:
                data = json.loads(message)

                if data["type"] == "event":
                    event = data["event"]
                    print(f"EVENT: {event['type']}")
                    print(f"   Stream: {event['stream_id']}")
                    print(f"   Execution: {event.get('execution_id', 'N/A')}")
                    print(f"   Data: {json.dumps(event['data'], indent=6)}")
                    print(f"   Timestamp: {event['timestamp']}")
                    print("=" * 60)
                elif data["type"] == "error":
                    print(f"ERROR: {data['message']}")
                else:
                    print(f"< {message}")

        except KeyboardInterrupt:
            print("\n\nDisconnecting...")


if __name__ == "__main__":
    asyncio.run(stream_client())
