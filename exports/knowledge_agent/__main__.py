import sys
import argparse
import json
import os

def main():
    # CHANGE 1: Update the CLI description
    parser = argparse.ArgumentParser(description="Knowledge Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate")
    subparsers.add_parser("info")
    
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--input", type=str)
    run_parser.add_argument("--mock", action="store_true")
    
    args = parser.parse_args()

    if args.command == "validate":
        json_path = os.path.join(os.path.dirname(__file__), "agent.json")
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            # This pulls the name dynamically from your agent.json, so it's safe
            print(f"✓ Agent structure valid: {data['goal']['name']}")
        except Exception as e:
            print(f"✗ Validation failed: {e}")
            sys.exit(1)

    elif args.command == "info":
        # CHANGE 2: Hardcode the correct identity here
        print("Agent: Knowledge Agent")
        print("Description: Autonomous research agent that searches the web and compiles summaries.")

    elif args.command == "run":
        if args.mock:
            print("Mock run executing...")
            # CHANGE 3: Update mock output to look like search results, not ticket data
            print("Result: {'summary': 'Aden is an autonomous agent framework...', 'sources': ['adenhq.com', 'github.com']}")
        else:
            print("Live run requires LLM credentials.")

if __name__ == "__main__":
    main()
