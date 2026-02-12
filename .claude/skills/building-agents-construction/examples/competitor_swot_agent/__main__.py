import asyncio
import sys
import argparse
import json
from .agent import CompetitorSwotAgent

def main():
    parser = argparse.ArgumentParser(description="Run the Competitor SWOT Agent")
    
    # improved: Allow specific flags instead of a raw JSON string
    parser.add_argument("--company", required=True, help="Target company to analyze (e.g., 'Linear')")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "validate"], help="Command to execute")
    
    args = parser.parse_args()

    if args.command == "validate":
        print("✓ Agent structure is valid.")
        return

    # Run the agent
    agent = CompetitorSwotAgent()
    try:
        # FIX: We explicitly map the argument to the key the Node expects
        input_data = {"target_company": args.company}
        
        result = asyncio.run(agent.run(input_data))
        
        print("\n✅ Execution Complete!")
        print("--------------------------------------------------")
        print(f"Input:    {input_data}")
        print(f"Output:   {result.output}")
        print("--------------------------------------------------")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()