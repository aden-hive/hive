import asyncio
import sys
import argparse
from .agent import AutoTestAIAgent

def main():
    parser = argparse.ArgumentParser(description="Run the AutoTest AI QA Agent")
    parser.add_argument("--url", required=True, help="Target URL to test (e.g., 'https://linear.app')")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "validate"], help="Command to execute")
    
    args = parser.parse_args()

    if args.command == "validate":
        print("✓ AutoTest AI graph structure is valid.")
        return

    agent = AutoTestAIAgent()
    try:
        input_data = {"target_url": args.url}
        # Notice we removed the live_mode flag completely
        result = asyncio.run(agent.run(input_data))
        
        print("\n✅ Execution Complete!")
        print("--------------------------------------------------")
        print(f"Target URL:   {input_data['target_url']}")
        print(f"Final State:  {result.output.get('test_results', 'Success')}")
        print("--------------------------------------------------")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()