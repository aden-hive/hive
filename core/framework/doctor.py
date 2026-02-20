"""
System health check and diagnostic tool.
"""
import importlib
import os
import shutil
import sys
from pathlib import Path

from framework.config import get_hive_config


def check_python_version() -> tuple[bool, str]:
    version = sys.version_info
    if version.major == 3 and version.minor >= 11:
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    return False, f"Python {version.major}.{version.minor} (Required: 3.11+)"


def check_dependencies() -> list[tuple[bool, str]]:
    results = []
    
    # Check uv
    uv_path = shutil.which("uv")
    if uv_path:
        results.append((True, f"uv found at {uv_path}"))
    else:
        results.append((False, "uv not found (Install from https://astral.sh/uv)"))

    # Check git
    git_path = shutil.which("git")
    if git_path:
        results.append((True, f"git found at {git_path}"))
    else:
        results.append((False, "git not found"))

    # Check nodejs (optional but good for some tools)
    node_path = shutil.which("node")
    if node_path:
        results.append((True, f"node found at {node_path}"))
    else:
        results.append((True, "node not found (Optional, recommended for JS tools)"))

    return results


def check_configuration() -> list[tuple[bool, str]]:
    results = []
    
    config_dir = Path.home() / ".hive"
    if not config_dir.exists():
         results.append((False, f"Configuration directory missing: {config_dir}"))
    else:
         results.append((True, f"Configuration directory exists: {config_dir}"))

    config_file = config_dir / "configuration.json"
    if config_file.exists():
        results.append((True, "configuration.json found"))
        try:
            get_hive_config()
            results.append((True, "configuration.json is valid"))
        except Exception:
            results.append((False, "configuration.json is invalid"))
    else:
        results.append((False, "configuration.json missing"))

    creds_file = config_dir / "credentials"
    if creds_file.exists():
        results.append((True, "Encrypted credentials store found"))
    else:
        results.append((True, "No encrypted credentials store (using env vars)"))

    return results


def run_doctor() -> int:
    """Run full health check."""
    print("Hive Doctor - System Health Check")
    print("=================================")
    print()

    # 1. Python
    print("Checking Python Environment...")
    ok, msg = check_python_version()
    print(f"  [{'OK' if ok else 'FAIL'}] {msg}")
    print()

    # 2. Dependencies
    print("Checking System Dependencies...")
    for ok, msg in check_dependencies():
        mark = "OK" if ok else "FAIL"
        if "Optional" in msg and not ok:
            mark = "WARN"
        print(f"  [{mark}] {msg}")
    print()

    # 3. Configuration
    print("Checking Configuration...")
    for ok, msg in check_configuration():
        print(f"  [{'OK' if ok else 'FAIL'}] {msg}")
    print()

    # 4. Agent Environment
    print("Checking Agent Environment...")
    # Check if we are in a valid agent directory
    cwd = Path.cwd()
    if (cwd / "agent.json").exists() or (cwd / "agent.py").exists():
        print(f"  [OK] Current directory looks like an agent: {cwd.name}")
        # Check tools.py
        if (cwd / "tools.py").exists():
            print("  [OK] tools.py found")
        else:
            print("  [INFO] No tools.py found")
    else:
        print("  [INFO] Not inside an agent directory (run from agent root to check specific agent)")

    print()
    print("Done.")
    return 0
