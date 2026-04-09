"""
CLI for support_ticket_agent.

Usage:
    python -m support_ticket_agent validate
    python -m support_ticket_agent info
    python -m support_ticket_agent run --input '{"ticket_content": "...", "customer_id": "...", "ticket_id": "..."}'
    python -m support_ticket_agent demo
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Support Ticket Agent - Process customer support tickets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "command",
        choices=["validate", "info", "run", "demo"],
        help="Command to execute",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock LLM responses (no API calls)",
    )
    parser.add_argument(
        "--input",
        type=str,
        help="JSON input data for 'run' command",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="cerebras/zai-glm-4.7",
        help="LLM model to use (default: cerebras/zai-glm-4.7)",
    )
    
    args = parser.parse_args()
    
    # Import framework components
    try:
        from framework.runner import AgentRunner
    except ImportError:
        print("Error: Could not import framework. Make sure you're running from the project root with:")
        print("  PYTHONPATH=core:exports python -m support_ticket_agent <command>")
        sys.exit(1)
    
    # Load agent
    agent_path = Path(__file__).parent
    try:
        runner = AgentRunner.load(
            agent_path,
            mock_mode=args.mock,
            model=args.model,
        )
    except Exception as e:
        print(f"Error loading agent: {e}")
        sys.exit(1)
    
    # Execute command
    if args.command == "validate":
        print("Validating agent structure...\n")
        result = runner.validate()
        
        if result.valid:
            print("Agent validation PASSED")
        else:
            print("Agent validation FAILED")
            
        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for error in result.errors:
                print(f"  - {error}")
                
        if result.warnings:
            print(f"\nWarnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  - {warning}")
                
        if result.missing_tools:
            print(f"\nMissing tools ({len(result.missing_tools)}):")
            for tool in result.missing_tools:
                print(f"  - {tool}")
                
        sys.exit(0 if result.valid else 1)
        
    elif args.command == "info":
        print("Agent Information\n")
        print("=" * 60)
        
        info = runner.info()
        
        print(f"Name: {info.name}")
        print(f"Description: {info.description}")
        print(f"Nodes: {info.node_count}")
        print(f"Edges: {info.edge_count}")
        print(f"Entry node: {info.entry_node}")
        print(f"Terminal nodes: {', '.join(info.terminal_nodes)}")
        
        print(f"\nGoal: {info.goal_name}")
        print(f"  {info.goal_description}")
        
        print(f"\nSuccess Criteria ({len(info.success_criteria)}):")
        for sc in info.success_criteria:
            print(f"  - {sc['description']} (weight: {sc.get('weight', 1.0)})")
            print(f"    Metric: {sc['metric']}, Target: {sc['target']}")
            
        print(f"\nConstraints ({len(info.constraints)}):")
        for c in info.constraints:
            print(f"  - {c['description']} ({c['type']})")
            
        print(f"\nNodes:")
        for node in info.nodes:
            print(f"  {node['id']} ({node['type']})")
            print(f"    {node['description']}")
            if node['input_keys']:
                print(f"    Inputs: {', '.join(node['input_keys'])}")
            if node['output_keys']:
                print(f"    Outputs: {', '.join(node['output_keys'])}")
            print()
            
        print(f"Required tools: {', '.join(info.required_tools) if info.required_tools else 'None'}")
        print(f"Has tools module: {info.has_tools_module}")
        
    elif args.command == "run":
        if not args.input:
            print("Error: --input is required for 'run' command")
            print("\nExample:")
            print('  python -m support_ticket_agent run --input \'{"ticket_content": "My login is broken", "customer_id": "CUST-123", "ticket_id": "TKT-456"}\'')
            sys.exit(1)
            
        try:
            input_data = json.loads(args.input)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON input: {e}")
            sys.exit(1)
            
        # Validate required keys
        required_keys = ["ticket_content", "customer_id", "ticket_id"]
        missing_keys = [k for k in required_keys if k not in input_data]
        if missing_keys:
            print(f"Error: Missing required input keys: {', '.join(missing_keys)}")
            print(f"Required keys: {', '.join(required_keys)}")
            sys.exit(1)
            
        print("Running agent...")
        if args.mock:
            print("(Using mock LLM mode - no API calls)\n")
        else:
            print(f"(Using model: {args.model})\n")
            
        try:
            result = await runner.run(input_data)
            
            if result.success:
                print("✅ Agent execution SUCCEEDED\n")
                print(f"Path taken: {' → '.join(result.path)}")
                print(f"\nOutput:")
                print(json.dumps(result.output, indent=2))
                print(f"\nMetrics:")
                print(f"  Total steps: {result.metrics.get('total_steps', 'N/A')}")
                print(f"  Total tokens: {result.metrics.get('total_tokens', 'N/A')}")
                print(f"  Total cost: ${result.metrics.get('total_cost', 0):.4f}")
                sys.exit(0)
            else:
                print("❌ Agent execution FAILED\n")
                print(f"Error: {result.error}")
                sys.exit(1)
                
        except Exception as e:
            print(f"❌ Execution error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
            
    elif args.command == "demo":
        print("Running demo with example ticket...\n")
        
        example_input = {
            "ticket_content": "My login is broken. I keep getting 'Error 401: Unauthorized' when I try to access my account. This started happening after the system maintenance yesterday. I need urgent help as I have a deadline today!",
            "customer_id": "CUST-12345",
            "ticket_id": "TKT-98765"
        }
        
        print("Input:")
        print(json.dumps(example_input, indent=2))
        print()
        
        if args.mock:
            print("(Using mock LLM mode - no API calls)\n")
        else:
            print(f"(Using model: {args.model})\n")
            
        try:
            result = await runner.run(example_input)
            
            if result.success:
                print("Demo execution SUCCEEDED\n")
                print(f"Path taken: {' → '.join(result.path)}")
                print(f"\nOutput:")
                print(json.dumps(result.output, indent=2))
                sys.exit(0)
            else:
                print("Demo execution FAILED\n")
                print(f"Error: {result.error}")
                sys.exit(1)
                
        except Exception as e:
            print(f"Execution error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
