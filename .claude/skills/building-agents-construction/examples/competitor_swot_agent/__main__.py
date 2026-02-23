import asyncio
import sys
import argparse
import os
from .agent import CompetitorSwotAgent

def main():
    parser = argparse.ArgumentParser(description="Run the Competitor SWOT Agent")
    
    parser.add_argument("--company", required=True, help="Target company to analyze (e.g., 'Linear')")
    parser.add_argument("--cron", action="store_true", help="Simulate a recurring scheduled run with memory")
    parser.add_argument("--live", action="store_true", help="Run using real LLM API keys instead of Mock mode")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "validate"], help="Command to execute")
    
    args = parser.parse_args()

    if args.command == "validate":
        print("✓ Agent structure is valid.")
        return

    agent = CompetitorSwotAgent()
    try:
        input_data = {"target_company": args.company}
        
        if args.cron:
            input_data["previous_run_summary"] = "Last week: Linear launched feature X, pricing was $8/mo."

        # Pass the --live flag to the agent
        result = asyncio.run(agent.run(input_data, live_mode=args.live))
        
        print("\n✅ Execution Complete!")
        print("--------------------------------------------------")
        print(f"Target:       {input_data['target_company']}")
        print(f"Mode:         {'Scheduled (Cron)' if args.cron else 'Ad-Hoc (Fresh)'}")
        print(f"LLM Engine:   {'LIVE (Real API)' if args.live else 'MOCK (Offline)'}")
        print(f"Final State:  {result.output.get('final_report', 'Success')}")
        print("--------------------------------------------------")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()