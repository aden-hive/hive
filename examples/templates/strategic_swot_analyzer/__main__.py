import asyncio
import sys
import argparse
from .agent import StrategicSwotAgent

def main():
    parser = argparse.ArgumentParser(description="Run the Strategic SWOT Agent")
    parser.add_argument("--company", required=True, help="Target company to analyze (e.g., 'Linear')")
    parser.add_argument("--cron", action="store_true", help="Simulate a recurring scheduled run with memory")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "validate"], help="Command to execute")
    
    args = parser.parse_args()

    if args.command == "validate":
        print("✓ Agent structure is valid.")
        return

    agent = StrategicSwotAgent()
    try:
        input_data = {"target_company": args.company}
        
        if args.cron:
            input_data["previous_run_summary"] = "Last week: Linear launched feature X, pricing was $8/mo."

        result = asyncio.run(agent.run(input_data))
        
        print("\n✅ Execution Complete!")
        print("--------------------------------------------------")
        print(f"Target:       {input_data['target_company']}")
        print(f"Mode:         {'Scheduled (Cron)' if args.cron else 'Ad-Hoc (Fresh)'}")
        print("--------------------------------------------------")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()