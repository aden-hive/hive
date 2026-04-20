#!/usr/bin/env python3
"""
Quick validation for CodeRabbit security fixes:
1. Sequence concatenation bypass (_safe_add)
2. Dict callable injection via dot-access
"""

import sys
from pathlib import Path

# Add core to path
core_path = Path(__file__).resolve().parent.parent / "core"
sys.path.insert(0, str(core_path))

from framework.orchestrator.safe_eval import safe_eval

print("=" * 70)
print("SECURITY FIX VALIDATION")
print("=" * 70)

# Test 1: Sequence concatenation bypass (CodeRabbit issue)
print("\n[1] Testing sequence concatenation guard (_safe_add)...")
try:
    result = safe_eval("[0] * 100000 + [1]")
    print(f"FAIL: Should have blocked concatenation, but got result: {len(result)} items")
except ValueError as e:
    if "collection size" in str(e).lower():
        print(f"✓ SUCCESS: Blocked concatenation bypass: {e}")
    else:
        print(f"FAIL: Wrong error: {e}")
except Exception as e:
    print(f"FAIL: Unexpected error: {type(e).__name__}: {e}")

# Test 2: Dict callable injection via dot-access (CodeRabbit issue)
print("\n[2] Testing dict dot-access callable injection prevention...")
try:
    # This would be a security hole: dict has "lower" key, "lower" is in method whitelist
    state = {"lower": lambda x: "HACKED"}
    result = safe_eval("state.lower()", {"state": state})
    print(f"FAIL: Should have blocked dict method call, but got: {result}")
except ValueError as e:
    if "not allowed" in str(e).lower():
        print(f"✓ SUCCESS: Blocked dict callable injection: {e}")
    else:
        print(f"FAIL: Wrong error: {e}")
except Exception as e:
    print(f"FAIL: Unexpected error: {type(e).__name__}: {e}")

# Test 3: Dict dot-access still works for safe methods (regression check)
print("\n[3] Testing dict dot-access still works for actual dict methods...")
try:
    state = {"user_id": 42, "name": "alice"}
    result = safe_eval("state.get('user_id')", {"state": state})
    if result == 42:
        print(f"✓ SUCCESS: dict.get() still works: {result}")
    else:
        print(f"FAIL: dict.get() returned wrong value: {result}")
except Exception as e:
    print(f"FAIL: dict.get() broken: {type(e).__name__}: {e}")

# Test 4: String method calls still work (regression check)
print("\n[4] Testing string methods still work...")
try:
    result = safe_eval("text.upper()", {"text": "hello"})
    if result == "HELLO":
        print(f"✓ SUCCESS: str.upper() still works: {result}")
    else:
        print(f"FAIL: str.upper() returned wrong value: {result}")
except Exception as e:
    print(f"FAIL: str.upper() broken: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print("VALIDATION COMPLETE")
print("=" * 70)
