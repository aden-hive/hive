#!/usr/bin/env python3
"""Command-line interface for the hello_world_agent."""
import json
import sys
import re
from exports.hello_world_agent.tools import echo_function

def validate():
    """Validate the agent structure."""
    print("✓ Hello World Agent")
    print("  This is a simple example agent for Hive")
    print("  It demonstrates basic agent structure")
    return True

def info():
    """Display agent information."""
    print("Hello World Agent")
    print("=" * 50)
    print("Goal: A simple example agent that demonstrates Hive agents")
    print("Success Criteria: Returns a greeting message")
    print("\nUsage:")
    print("  python -m hello_world_agent validate")
    print("  python -m hello_world_agent info")
    print('  python -m hello_world_agent run --input \'{"name": "World"}\'')
    print("\nNote: On Windows PowerShell, use:")
    print('  python -m hello_world_agent run --input \'{\\"name\\": \\"Test\\"}\'')

def parse_json_input(input_str):
    """Parse JSON input, handling platform-specific quirks."""
    # Try direct parse first
    try:
        return json.loads(input_str)
    except json.JSONDecodeError:
        pass
    
    # Handle common issues
    # 1. Replace escaped quotes
    input_str = input_str.replace('\\"', '"')
    # 2. Replace single quotes with double quotes
    input_str = re.sub(r"'([^']*)'", r'"\1"', input_str)
    # 3. Remove extra backslashes
    input_str = input_str.replace('\\\\', '\\')
    
    try:
        return json.loads(input_str)
    except json.JSONDecodeError as e:
        print(f"Error parsing input JSON: {e}")
        print(f"Input received: {sys.argv[3]}")
        print("\nTry these formats:")
        print('  Linux/Mac:   --input \'{"name": "Test"}\'')
        print('  PowerShell:  --input \'{\\"name\\": \\"Test\\"}\'')
        print('  CMD:         --input "{""name"": ""Test""}"')
        raise

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        info()
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "validate":
        validate()
    
    elif command == "info":
        info()
    
    elif command == "run":
        if len(sys.argv) < 4 or sys.argv[2] != "--input":
            print("Usage: python -m hello_world_agent run --input 'JSON_STRING'")
            print("\nExamples:")
            print('  --input \'{"name": "Alice"}\'')
            print('  --input \'{\\"name\\": \\"Bob\\"}\' (Windows PowerShell)')
            sys.exit(1)
        
        try:
            input_data = parse_json_input(sys.argv[3])
            name = input_data.get("name", "World")
            result = echo_function(name)
            print(json.dumps(result, indent=2))
        except (json.JSONDecodeError, ValueError):
            sys.exit(1)
    
    else:
        print(f"Unknown command: {command}")
        print("Available commands: validate, info, run")
        sys.exit(1)

if __name__ == "__main__":
    main()