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
import time
import importlib.metadata
from typing import Dict, List, Union


def check_imports(modules: List[str]) -> Dict[str, Union[str, Dict]]:
    """
    Attempt to import each module and return status.

    Args:
        modules: List of module names to check

    Returns:
        Dictionary mapping module name to status with details
    """
    results = {}
    failed_modules = []

    for module_name in modules:
        module_start = time.time()
        
        try:
            # Validate module name format
            if " " in module_name or ("." in module_name and module_name.count(".") > 3):
                results[module_name] = {
                    "status": "error",
                    "message": "invalid module name format",
                    "time": f"{time.time() - module_start:.3f}s"
                }
                failed_modules.append(module_name)
                continue

            # Try to import the module
            module = __import__(module_name)
            
            # Get version if available
            try:
                version = importlib.metadata.version(module_name)
                version_info = version
            except (importlib.metadata.PackageNotFoundError, Exception):
                version_info = "unknown"
            
            # Get module path if available
            module_path = getattr(module, "__file__", "unknown")
            
            elapsed = time.time() - module_start
            results[module_name] = {
                "status": "ok",
                "version": version_info,
                "path": module_path,
                "time": f"{elapsed:.3f}s"
            }
            
        except ImportError as e:
            elapsed = time.time() - module_start
            error_msg = str(e)
            results[module_name] = {
                "status": "error",
                "type": "ImportError",
                "message": f"module '{module_name}' not found - {error_msg}",
                "time": f"{elapsed:.3f}s"
            }
            failed_modules.append(module_name)
            
        except Exception as e:
            elapsed = time.time() - module_start
            results[module_name] = {
                "status": "error",
                "type": type(e).__name__,
                "message": f"error importing '{module_name}': {str(e)}",
                "time": f"{elapsed:.3f}s"
            }
            failed_modules.append(module_name)

    return {
        "results": results,
        "summary": {
            "total": len(modules),
            "success": len(modules) - len(failed_modules),
            "failed": len(failed_modules),
            "failed_modules": failed_modules,
            "total_time": f"{time.time() - time_start:.3f}s"
        }
    }


def print_summary(data: Dict) -> None:
    """Print human-readable summary to stderr."""
    summary = data["summary"]
    
    print("\n" + "="*50, file=sys.stderr)
    print("📊 IMPORT CHECK SUMMARY", file=sys.stderr)
    print("="*50, file=sys.stderr)
    print(f"   ✅ Success: {summary['success']}", file=sys.stderr)
    print(f"   ❌ Failed: {summary['failed']}", file=sys.stderr)
    print(f"   📦 Total: {summary['total']}", file=sys.stderr)
    print(f"   ⏱️  Time: {summary['total_time']}", file=sys.stderr)
    
    if summary['failed'] > 0:
        print("\n❌ Failed modules:", file=sys.stderr)
        for module in summary['failed_modules']:
            print(f"   - {module}", file=sys.stderr)
    
    print("="*50 + "\n", file=sys.stderr)


def main():
    """Main entry point."""
    global time_start
    time_start = time.time()
    
    if len(sys.argv) < 2:
        error_response = {
            "error": "No modules specified",
            "usage": "python scripts/check_requirements.py <module1> <module2> ..."
        }
        print(json.dumps(error_response, indent=2), file=sys.stderr)
        sys.exit(1)

    modules_to_check = [m for m in sys.argv[1:] if m and not m.startswith("-")]
    
    if not modules_to_check:
        error_response = {
            "error": "No valid modules specified",
            "usage": "python scripts/check_requirements.py <module1> <module2> ..."
        }
        print(json.dumps(error_response, indent=2), file=sys.stderr)
        sys.exit(1)

    # Run import checks
    result_data = check_imports(modules_to_check)
    
    # Print human-readable summary
    print_summary(result_data)
    
    # Print JSON results for programmatic use
    print(json.dumps(result_data, indent=2))

    # Exit with error code if any imports failed
    sys.exit(1 if result_data["summary"]["failed"] > 0 else 0)


# Global for timing
time_start = 0

if __name__ == "__main__":
    main()
