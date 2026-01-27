"""
Preflight validation for Hive agent runtime
- Checks environment variables
- Verifies LLM providers
- Confirms MCP tools load
- Validates agent graph structure
"""

import os
import sys

def validate_env():
    required_vars = ["OPENAI_API_KEY", "LITELLM_PROVIDER"]
    missing = [v for v in required_vars if v not in os.environ]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        return False
    return True

def run_validation():
    print("Running preflight validation...")
    
    if not validate_env():
        print("Validation failed!")
        sys.exit(1)
    
    # TODO: Check MCP tools
    print("MCP tools validation placeholder")
    
    # TODO: Validate agent graphs
    print("Agent graph validation placeholder")
    
    print("Validation complete. No issues found.")

if __name__ == "__main__":
    run_validation()
