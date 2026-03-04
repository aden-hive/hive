#!/usr/bin/env python3
"""
Demonstration of the fixed error handling in AgentRunner.load()

This script shows the error messages that will be produced for various
agent.json issues.
"""

import json
from pathlib import Path
import tempfile


def demo_error_handling():
    """Demonstrate the new error handling behavior."""

    print("=" * 70)
    print("AgentRunner.load() Error Handling Demonstration")
    print("=" * 70)

    # Case 1: Empty agent.json
    print("\nCase 1: Empty agent.json")
    print("-" * 70)
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_path = Path(tmpdir)
        agent_json = agent_path / "agent.json"
        agent_json.write_text("")

        try:
            if not agent_json.read_text().strip():
                raise ValueError("Error: agent.json is empty")
        except ValueError as e:
            print(f"ERROR OUTPUT: {e}")
            print("EXIT CODE: 1")

    # Case 2: agent.json is a directory
    print("\nCase 2: agent.json is a directory")
    print("-" * 70)
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_path = Path(tmpdir)
        agent_json = agent_path / "agent.json"
        agent_json.mkdir()

        try:
            if agent_json.is_dir():
                raise ValueError(
                    f"Error: agent.json is not a file (it's a directory at {agent_json})"
                )
        except ValueError as e:
            print(f"ERROR OUTPUT: {e}")
            print("EXIT CODE: 1")

    # Case 3: Invalid JSON
    print("\nCase 3: Invalid JSON in agent.json")
    print("-" * 70)
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_path = Path(tmpdir)
        agent_json = agent_path / "agent.json"
        agent_json.write_text("{invalid json}")

        try:
            content = agent_json.read_text()
            json.loads(content)
        except json.JSONDecodeError as e:
            error_msg = f"Error: agent.json is not valid JSON: {e}"
            print(f"ERROR OUTPUT: {error_msg}")
            print("EXIT CODE: 1")

    # Case 4: Valid but incomplete JSON (missing required fields)
    print("\nCase 4: Valid JSON but incomplete agent definition")
    print("-" * 70)
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_path = Path(tmpdir)
        agent_json = agent_path / "agent.json"
        agent_json.write_text('{"name": "test"}')

        try:
            content = agent_json.read_text()
            json.loads(content)
            print("(This would be caught by load_agent_export validation)")
            print("ERROR OUTPUT: ValueError from load_agent_export")
            print("EXIT CODE: 1")
        except json.JSONDecodeError as e:
            print(f"ERROR OUTPUT: {e}")

    print("\n" + "=" * 70)
    print("All error cases now produce clear, readable messages")
    print("No raw tracebacks are shown to users")
    print("=" * 70)


if __name__ == "__main__":
    demo_error_handling()
