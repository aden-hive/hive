#!/usr/bin/env python3
"""
Simple test script to verify check_requirements.py works correctly
"""

import subprocess
import json
import sys


def test_check_requirements():
    """Test the check_requirements.py script"""

    print("Testing check_requirements.py...")
    print("=" * 60)

    # Test 1: All valid modules
    print("\n Test 1: All valid standard library modules")
    result = subprocess.run(
        [sys.executable, "scripts/check_requirements.py", "json", "sys", "os"],
        capture_output=True,
        text=True,
    )
    print(f"Exit code: {result.returncode}")
    print(f"Output:\n{result.stdout}")

    try:
        data = json.loads(result.stdout)
        assert all(v == "ok" for v in data.values()), "All modules should be 'ok'"
        assert result.returncode == 0, "Exit code should be 0"
        print("✓ Test 1 passed")
    except Exception as e:
        print(f"✗ Test 1 failed: {e}")
        return False

    # Test 2: Mix of valid and invalid modules
    print("\n\nTest 2: Mix of valid and invalid modules")
    result = subprocess.run(
        [sys.executable, "scripts/check_requirements.py", "json", "nonexistent_module"],
        capture_output=True,
        text=True,
    )
    print(f"Exit code: {result.returncode}")
    print(f"Output:\n{result.stdout}")

    try:
        data = json.loads(result.stdout)
        assert data["json"] == "ok", "json should be ok"
        assert "error" in data["nonexistent_module"], (
            "nonexistent_module should have error"
        )
        assert result.returncode == 1, "Exit code should be 1 when errors exist"
        print("✓ Test 2 passed")
    except Exception as e:
        print(f"✗ Test 2 failed: {e}")
        return False

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    return True


if __name__ == "__main__":
    success = test_check_requirements()
    sys.exit(0 if success else 1)
