"""CLI entry point for LinkedIn ABM Agent."""

import asyncio

from .agent import LinkedInABMAgent


def main():
    """Run the LinkedIn ABM Agent interactively."""
    agent = LinkedInABMAgent()

    print(f"\n{agent.info()['name']} v{agent.info()['version']}")
    print("=" * 50)
    print(agent.info()["description"])
    print("\nStarting agent...\n")

    asyncio.run(agent.start())

    try:
        result = asyncio.run(agent.trigger_and_wait("default", {}))
        print("\n" + "=" * 50)
        print("Execution completed.")
        if result:
            print(f"Success: {result.success}")
            if result.error:
                print(f"Error: {result.error}")
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        asyncio.run(agent.stop())


if __name__ == "__main__":
    main()
