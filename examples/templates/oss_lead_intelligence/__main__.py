"""
OSS Lead Intelligence Agent - CLI Entry Point.

Usage:
    cd core && uv run python -m oss_lead_intelligence [command]

Commands:
    run      - Run the agent interactively
    info     - Show agent information
    validate - Validate the agent graph
"""

import asyncio
import sys


def main():
    if len(sys.argv) < 2:
        command = "run"
    else:
        command = sys.argv[1]

    if command == "info":
        _show_info()
    elif command == "validate":
        _validate()
    elif command == "run":
        asyncio.run(_run())
    else:
        print(f"Unknown command: {command}")
        print("Usage: python -m oss_lead_intelligence [run|info|validate]")
        sys.exit(1)


def _show_info():
    from . import default_agent, metadata

    print(f"Agent: {metadata.name}")
    print(f"Version: {metadata.version}")
    print(f"Description: {metadata.description}")
    print()
    print("Nodes:")
    for node in default_agent.nodes:
        print(f"  - {node.id}: {node.name}")
    print()
    print("Edges:")
    for edge in default_agent.edges:
        print(f"  - {edge.source} -> {edge.target} ({edge.condition})")
    print()
    print(f"Entry Node: {default_agent.entry_node}")
    print(f"Terminal Nodes: {default_agent.terminal_nodes}")


def _validate():
    from . import default_agent

    result = default_agent.validate()
    if result["valid"]:
        print("Agent graph is valid!")
    else:
        print("Validation errors:")
        for error in result["errors"]:
            print(f"  - {error}")
        sys.exit(1)


async def _run():
    from . import default_agent, metadata

    print(metadata.intro_message)
    print()
    print("Starting OSS Lead Intelligence Agent...")
    print("Press Ctrl+C to stop.")
    print()

    try:
        await default_agent.start()
        result = await default_agent.trigger_and_wait("default")
        if result:
            print(f"\nExecution completed: {result.success}")
            if result.error:
                print(f"Error: {result.error}")
        else:
            print("\nNo result returned.")
    except KeyboardInterrupt:
        print("\nStopping agent...")
    finally:
        await default_agent.stop()


if __name__ == "__main__":
    main()
