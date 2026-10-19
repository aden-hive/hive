#!/usr/bin/env python3
"""
check_requirements.py - Batch import checker for quickstart scripts

This script checks multiple Python module imports in a single process,
reducing subprocess spawning overhead significantly on Windows.

Usage:
    python scripts/check_requirements.py <module1> <module2> ...

Returns:
    JSON object with import status for each module
    Exit code 0 if all imports succeed, 1 if any fail
"""

import json
import sys
from typing import Dict


def check_imports(modules: list[str]) -> Dict[str, str]:
    """
    Attempt to import each module and return status.

    Args:
        modules: List of module names to check

    Returns:
        Dictionary mapping module name to "ok" or error message
    """
    results = {}

    for module_name in modules:
        try:
            # Handle both simple imports and from imports
            if " " in module_name:
                # This shouldn't happen with current usage, but handle it safely
                results[module_name] = "error: invalid module name"
            else:
                # Try to import the module
                __import__(module_name)
                results[module_name] = "ok"
        except ImportError as e:
            results[module_name] = f"error: {str(e)}"
        except Exception as e:
            results[module_name] = f"error: {type(e).__name__}: {str(e)}"

    return results


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No modules specified"}), file=sys.stderr)
        sys.exit(1)

    modules_to_check = sys.argv[1:]
    results = check_imports(modules_to_check)

    # Print results as JSON
    print(json.dumps(results, indent=2))

    # Exit with error code if any imports failed
    has_errors = any(status != "ok" for status in results.values())
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
