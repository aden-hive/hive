"""CLI entry point for Coding Agent."""

import asyncio
import json
import sys
from .agent import default_agent

async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m examples.templates.coding_agent '<json_input>'")
        sys.exit(1)

    try:
        input_data = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        print("Error: Input must be valid JSON")
        sys.exit(1)

    print(f"Running Coding Agent request: {input_data.get('request', 'Unknown')}")
    result = await default_agent.run(input_data)

    print("\n=== Result ===")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
