"""CLI for the Q&A Agent."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cli():
    """Entry point for the Q&A Agent command-line interface.

    Parses arguments and executes the requested command (currently only 'run').
    """
    parser = argparse.ArgumentParser(description="Q&A Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run command
    run_parser = subparsers.add_parser("run", help="Run the agent")
    run_parser.add_argument(
        "--input", type=str, default="{}", help="Input JSON string"
    )

    args = parser.parse_args()

    if args.command == "run":
        try:
            input_data = json.loads(args.input)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input")
            return

        # Adjust path for import if run directly
        if __package__ is None:
            sys.path.append(str(Path(__file__).parents[2]))
            from exports.qanda_python.agent import default_agent
        else:
            from .agent import default_agent

        async def run_agent():
            """Runs the agent with input data and prints the result."""
            print("=== Q&A Agent ===")
            print(f"Question: {input_data.get('question', 'No question provided')}")
            print("Running...")
            result = await default_agent.run(input_data)
            if result.success:
                print("\nSuccess!")
                print(f"Answer: {result.output.get('answer')}")
            else:
                print(f"\nFailed: {result.error if hasattr(result, 'error') else 'Unknown error'}")
                if hasattr(result, 'error') and result.error:
                    print(f"Error details: {result.error}")

        asyncio.run(run_agent())


if __name__ == "__main__":
    cli()
