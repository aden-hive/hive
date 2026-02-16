"""CLI entry point for Contract Evaluation Agent."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .agent import default_agent


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Contract Evaluation Agent")
    parser.add_argument(
        "command",
        choices=["run", "info", "validate"],
        help="Command to execute"
    )
    parser.add_argument(
        "--contract-path",
        "-c",
        help="Path to contract file (PDF/DOCX)"
    )
    parser.add_argument(
        "--input",
        "-i",
        help="JSON input data"
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output file path for report"
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Run with TUI dashboard"
    )

    args = parser.parse_args()

    if args.command == "info":
        info = default_agent.info()
        print(json.dumps(info, indent=2))
        return 0

    if args.command == "validate":
        try:
            default_agent.validate()
            print("✓ Agent structure is valid")
            return 0
        except Exception as e:
            print(f"✗ Validation failed: {e}")
            return 1

    if args.command == "run":
        # Prepare input data
        if args.input:
            input_data = json.loads(args.input)
        elif args.contract_path:
            input_data = {"contract_path": args.contract_path}
        else:
            print("Error: Must provide either --contract-path or --input")
            return 1

        # Run the agent
        try:
            result = asyncio.run(default_agent.run(input_data))
            
            # Print or save report
            if result.get("report_markdown"):
                report = result["report_markdown"]
                if args.output:
                    Path(args.output).write_text(report)
                    print(f"✓ Report saved to {args.output}")
                else:
                    print(report)
            
            # Print JSON summary
            if result.get("report_json"):
                json_path = args.output.replace(".md", ".json") if args.output else None
                if json_path:
                    Path(json_path).write_text(json.dumps(result["report_json"], indent=2))
                    print(f"✓ JSON report saved to {json_path}")
            
            return 0
            
        except Exception as e:
            print(f"✗ Execution failed: {e}")
            import traceback
            traceback.print_exc()
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
