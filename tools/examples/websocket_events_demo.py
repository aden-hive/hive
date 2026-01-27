"""
Demo script to publish events to the EventBus for testing WebSocket streaming.

This simulates an agent execution by publishing various events.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from framework.runtime.event_bus import EventBus


async def demo_agent_execution():
    """Simulate an agent execution by publishing events."""
    bus = EventBus()

    print("Publishing demo agent execution events...")
    print("=" * 60)

    print("Step 1: Publishing EXECUTION_STARTED...")
    await bus.emit_execution_started(
        stream_id="demo_agent",
        execution_id="exec_demo_001",
        input_data={"query": "Build a customer support ticket classifier"},
        correlation_id="demo_corr_001",
    )
    await asyncio.sleep(1)

    print("Step 2: Publishing GOAL_PROGRESS (25%)...")
    await bus.emit_goal_progress(
        stream_id="demo_agent",
        progress=0.25,
        criteria_status={
            "data_collected": "completed",
            "model_trained": "in_progress",
            "deployed": "pending",
        },
    )
    await asyncio.sleep(1.5)

    print("Step 3: Publishing GOAL_PROGRESS (50%)...")
    await bus.emit_goal_progress(
        stream_id="demo_agent",
        progress=0.50,
        criteria_status={
            "data_collected": "completed",
            "model_trained": "completed",
            "deployed": "in_progress",
        },
    )
    await asyncio.sleep(1.5)

    print("Step 4: Publishing STATE_CHANGED...")
    await bus.emit_state_changed(
        stream_id="demo_agent",
        execution_id="exec_demo_001",
        key="model_accuracy",
        old_value=0.82,
        new_value=0.91,
        scope="execution",
    )
    await asyncio.sleep(1)

    print("Step 5: Publishing GOAL_PROGRESS (75%)...")
    await bus.emit_goal_progress(
        stream_id="demo_agent",
        progress=0.75,
        criteria_status={
            "data_collected": "completed",
            "model_trained": "completed",
            "deployed": "in_progress",
        },
    )
    await asyncio.sleep(1.5)

    print("Step 6: Publishing GOAL_PROGRESS (100% - Goal Achieved)...")
    await bus.emit_goal_progress(
        stream_id="demo_agent",
        progress=1.0,
        criteria_status={
            "data_collected": "completed",
            "model_trained": "completed",
            "deployed": "completed",
        },
    )
    await asyncio.sleep(1)

    print("Step 7: Publishing EXECUTION_COMPLETED...")
    await bus.emit_execution_completed(
        stream_id="demo_agent",
        execution_id="exec_demo_001",
        output={
            "status": "success",
            "model_id": "ticket_classifier_v1",
            "accuracy": 0.91,
            "deployment_url": "https://api.example.com/classifier",
        },
        correlation_id="demo_corr_001",
    )

    print("\nAll events published!")
    print("=" * 60)

    stats = bus.get_stats()
    print("\nEventBus Stats:")
    print(f"   Total events: {stats['total_events']}")
    print(f"   Subscriptions: {stats['subscriptions']}")
    print("   Events by type:")
    for event_type, count in stats["events_by_type"].items():
        print(f"      {event_type}: {count}")


if __name__ == "__main__":
    print("Warning: This demo uses a local EventBus instance.")
    print("   To see events in the WebSocket client, the EventBus must be shared.")
    print("   Run the WebSocket server in the same process for live streaming.\n")
    asyncio.run(demo_agent_execution())
