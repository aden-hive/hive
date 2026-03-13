"""CLI entry point for SDR Agent."""

import asyncio
import json
import sys

from .agent import default_agent

async def main():
    """Run the agent from command line args."""
    if len(sys.argv) < 2:
        print("Usage: python -m examples.templates.sdr_agent <input_json>")
        sys.exit(1)

    try:
        input_data = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        print("Error: Input must be valid JSON")
        sys.exit(1)

    print(f"Running SDR Agent for prospect: {input_data.get('prospect_name', 'Unknown')}")
    result = await default_agent.run(input_data)

    print("\n=== Result ===")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
