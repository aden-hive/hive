"""
Full integration test: Server + Client + Event Publisher

Demonstrates the complete streaming workflow:
1. Start WebSocket server
2. Connect client
3. Publish events from agent execution
4. Client receives events in real-time
"""

import asyncio
import json
import sys
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))

from framework.runtime.event_bus import EventBus
from framework.runtime.websocket_server import WebSocketServer


async def run_integration_test():
    """Run full integration test."""
    print("=" * 70)
    print("HIVE WEBSOCKET STREAMING - INTEGRATION TEST")
    print("=" * 70)
    print()

    print("Step 1: Creating EventBus...")
    bus = EventBus()

    print("Step 2: Starting WebSocket server on ws://localhost:9999...")
    server = WebSocketServer(event_bus=bus, host="localhost", port=9999)
    await server.start()
    await asyncio.sleep(0.5)

    print("Step 3: Connecting WebSocket client...")
    uri = "ws://localhost:9999"

    events_received: list[dict] = []

    async def client_task():
        """Client that receives events."""
        async with websockets.connect(uri) as ws:
            welcome = await ws.recv()
            print(f"   Client connected: {json.loads(welcome)['message']}")

            await ws.send(json.dumps({"action": "subscribe"}))
            await ws.recv()
            print("   Client subscribed")
            print("   Listening for events...\n")

            try:
                async for message in ws:
                    data = json.loads(message)
                    if data["type"] == "event":
                        event = data["event"]
                        events_received.append(event)
                        print(f"   Received: {event['type']} (stream: {event['stream_id']})")

                        if event["type"] == "execution_completed":
                            await asyncio.sleep(0.1)
                            return
            except websockets.exceptions.ConnectionClosed:
                pass

    async def publisher_task():
        """Publisher that emits agent events."""
        await asyncio.sleep(1)

        print("Step 4: Publishing agent execution events...\n")

        await bus.emit_execution_started(
            stream_id="test_agent",
            execution_id="exec_test_001",
            input_data={"task": "Process customer feedback"},
        )
        print("   Published: EXECUTION_STARTED")
        await asyncio.sleep(0.5)

        await bus.emit_goal_progress(
            stream_id="test_agent",
            progress=0.33,
            criteria_status={"collect_feedback": "completed", "analyze": "in_progress"},
        )
        print("   Published: GOAL_PROGRESS (33%)")
        await asyncio.sleep(0.5)

        await bus.emit_goal_progress(
            stream_id="test_agent",
            progress=0.66,
            criteria_status={"collect_feedback": "completed", "analyze": "completed"},
        )
        print("   Published: GOAL_PROGRESS (66%)")
        await asyncio.sleep(0.5)

        await bus.emit_goal_progress(
            stream_id="test_agent",
            progress=1.0,
            criteria_status={"collect_feedback": "completed", "analyze": "completed", "report": "completed"},
        )
        print("   Published: GOAL_PROGRESS (100%)")
        await asyncio.sleep(0.5)

        await bus.emit_execution_completed(
            stream_id="test_agent",
            execution_id="exec_test_001",
            output={"status": "success", "insights": 42},
        )
        print("   Published: EXECUTION_COMPLETED\n")

    try:
        await asyncio.gather(client_task(), publisher_task())
    except Exception as exc:  # pragma: no cover - diagnostic output only
        print(f"   Error: {exc}")

    print("Step 5: Verifying results...")
    print(f"   Events received: {len(events_received)}")

    expected_types = [
        "execution_started",
        "goal_progress",
        "goal_progress",
        "goal_progress",
        "execution_completed",
    ]

    received_types = [event["type"] for event in events_received]

    if received_types == expected_types:
        print("   All events received in correct order!")
    else:
        print("   Event mismatch!")
        print(f"      Expected: {expected_types}")
        print(f"      Received: {received_types}")

    stats = bus.get_stats()
    print("\nStep 6: EventBus Statistics:")
    print(f"   Total events: {stats['total_events']}")
    print(f"   Subscriptions: {stats['subscriptions']}")

    server_stats = server.get_stats()
    print("\nStep 7: WebSocket Server Statistics:")
    print(f"   Connected clients: {server_stats['connected_clients']}")
    print(f"   Active subscriptions: {server_stats['subscriptions']}")

    print("\nStep 8: Shutting down...")
    await server.stop()

    print()
    print("=" * 70)
    print("INTEGRATION TEST COMPLETE!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_integration_test())
