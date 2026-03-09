"""Entry point for running the Agent QA Pipeline agent."""

import asyncio
import sys

from .agent import default_agent


async def main():
    """Run the Agent QA Pipeline agent."""
    print("Starting Agent QA Pipeline...")
    print("=" * 50)

    try:
        await default_agent.start()
        print("\nAgent QA Pipeline is running!")
        print("Provide an agent spec to analyze (file path or raw JSON).")

        result = await default_agent.trigger_and_wait(
            entry_point="default",
            input_data={},
        )

        if result:
            print(f"\nExecution completed: {'Success' if result.success else 'Failed'}")
            if result.error:
                print(f"Error: {result.error}")
        else:
            print("\nNo result returned from execution")

    except KeyboardInterrupt:
        print("\n\nShutting down...")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        await default_agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
