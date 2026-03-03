"""CLI entry point for OSS Contributor Accelerator template."""

import json
import sys
from pathlib import Path

from framework.runner.tool_registry import ToolRegistry
from framework.tools.builtins import register_builtin_tools

from .agent import OSSContributorAccelerator
from .config import default_config


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m oss_contributor_accelerator '<json_input>'")
        print("Example: python -m oss_contributor_accelerator '{\"initial_request\": \"I want to contribute to React\"}'")
        sys.exit(1)
    
    try:
        # Parse input
        input_json = sys.argv[1] if len(sys.argv) > 1 else "{}"
        input_data = json.loads(input_json)
        
        # Validate required input
        if "initial_request" not in input_data:
            print("Error: 'initial_request' is required in input")
            print("Example: {\"initial_request\": \"I want to contribute to React\"}")
            sys.exit(1)
        
        # Create agent and tool registry
        agent = OSSContributorAccelerator(default_config)
        tool_registry = ToolRegistry()
        register_builtin_tools(tool_registry)
        
        # Execute agent
        print("🚀 Starting OSS Contributor Accelerator...")
        print(f"📝 Initial request: {input_data['initial_request']}")
        print()
        
        result = agent.execute(input_data, tool_registry)
        
        # Display results
        print("✅ Execution completed!")
        print()
        
        if result.success:
            print("🎯 Success!")
            if result.outputs:
                print("📋 Outputs:")
                for key, value in result.outputs.items():
                    if key == "contribution_brief":
                        print(f"  📄 {key}: {value}")
                        # Try to read and display a preview of the brief
                        try:
                            brief_path = Path(value)
                            if brief_path.exists():
                                with open(brief_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                    lines = content.split('\n')
                                    preview = '\n'.join(lines[:20])  # First 20 lines
                                    print(f"📖 Preview:")
                                    print(preview)
                                    if len(lines) > 20:
                                        print(f"... ({len(lines) - 20} more lines)")
                        except Exception as e:
                            print(f"  • {key}: {value} (could not preview: {e})")
                    else:
                        print(f"  • {key}: {value}")
            
            if result.metrics:
                print("📊 Metrics:")
                for key, value in result.metrics.items():
                    print(f"  • {key}: {value}")
        else:
            print("❌ Execution failed")
            if result.error:
                print(f"Error: {result.error}")
        
        # Save results to file
        output_file = Path("oss_contributor_accelerator_result.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "success": result.success,
                "outputs": result.outputs,
                "metrics": result.metrics,
                "error": result.error,
                "execution_time": result.execution_time,
            }, f, indent=2, default=str)
        
        print(f"\n💾 Results saved to: {output_file}")
        
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON input - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
