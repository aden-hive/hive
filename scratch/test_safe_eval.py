
import sys
from pathlib import Path

# Core package root (…/hive/hive/core) — portable for any clone location
_core = Path(__file__).resolve().parent.parent / "core"
if _core.is_dir():
    sys.path.insert(0, str(_core))

from framework.orchestrator.safe_eval import safe_eval

def test_resource_exhaustion():
    print("Testing resource exhaustion (List Multiplication)...")
    try:
        # Should now be blocked by MAX_COLLECTION_SIZE
        safe_eval("[0] * 100001", timeout_ms=1000)
    except ValueError as e:
        print(f"SUCCESS: Blocked large collection: {e}")
    except Exception as e:
        print(f"FAILED: Unexpected error: {type(e).__name__}: {e}")

def test_dot_dict_support():
    print("\nTesting DotDict support...")
    context = {"state": {"user_id": 123}}
    try:
        result = safe_eval("state.user_id", context=context)
        if result == 123:
            print("SUCCESS: DotDict access worked")
        else:
            print(f"FAILED: Wrong result: {result}")
    except Exception as e:
        print(f"FAILED: Got error: {type(e).__name__}: {e}")

def test_recursion_limit():
    print("\nTesting recursion limit...")
    try:
        # Heavily nested expression that ast.parse might allow but visitor should block
        # Actually ast.parse has its own limit, but let's try a deep attribute chain
        expr = "a" + ".b" * 150
        class Node:
            def __getattr__(self, name): return self
        context = {"a": Node()}
        safe_eval(expr, context=context)
    except ValueError as e:
        if "Recursion depth limit exceeded" in str(e):
            print(f"SUCCESS: Blocked deep recursion: {e}")
        else:
            print(f"FAILED: Unexpected ValueError: {e}")
    except Exception as e:
        print(f"FAILED: Unexpected error: {type(e).__name__}: {e}")

def test_private_attribute_bypass():
    print("\nTesting private attribute bypass...")
    class TestObj:
        def __init__(self):
            self.public = "hi"
            self._private = "secret"
    
    context = {"obj": TestObj()}
    try:
        safe_eval("obj._private", context=context)
        print("FAILED: Accessed _private")
    except ValueError as e:
        print(f"SUCCESS: Blocked _private: {e}")

if __name__ == "__main__":
    test_resource_exhaustion()
    test_dot_dict_support()
    test_recursion_limit()
    test_private_attribute_bypass()
