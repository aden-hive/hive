import json
import time
import sys
import unittest
from framework.graph.output_cleaner import OutputCleaner, CleansingConfig, _heuristic_repair

# Increase recursion limit just in case the test runner needs it
sys.setrecursionlimit(2000)

class TestJsonDos(unittest.TestCase):
    def test_large_string_parsing(self):
        """Demonstrate that current code attempts to parse massive strings."""
        # Create a 5MB JSON string
        large_json = '{"data": "' + "x" * (5 * 1024 * 1024) + '"}'
        
        print(f"\nCreated JSON string of size: {len(large_json) / 1024 / 1024:.2f} MB")
        
        start_time = time.time()
        try:
            # This calls json.loads internaly via _heuristic_repair or similar paths
            # The current implementation SHOULD succeed in parsing this (consuming memory)
            # After fix, this might be skipped or raise an error
            result = _heuristic_repair(large_json)
            duration = time.time() - start_time
            print(f"Parsed successfully in {duration:.4f}s")
        except Exception as e:
            print(f"Parsing failed: {e}")

    def test_deep_nesting(self):
        """Demonstrate deep nesting parsing."""
        depth = 2000
        deep_json = ('[' * depth) + (']' * depth)
        
        print(f"\nCreated deeply nested JSON with depth: {depth}")
        
        try:
            # Python's default json.loads might handle this or hit recursion limit depending on version
            # The goal of the fix is to explicitly reject it
            import json
            json.loads(deep_json)
            print("Standard json.loads accepted deep nesting")
        except RecursionError:
            print("Standard json.loads hit RecursionError")
        except Exception as e:
            print(f"Standard json.loads failed: {e}")

if __name__ == "__main__":
    unittest.main()
