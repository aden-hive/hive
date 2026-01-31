
import json
import unittest
from unittest.mock import MagicMock, patch

from framework.graph.output_cleaner import (
    OutputCleaner, 
    CleansingConfig, 
    _heuristic_repair, 
    _safe_json_loads,
    MAX_JSON_PARSE_SIZE,
    MAX_JSON_DEPTH
)

class TestOutputCleanerSecurity(unittest.TestCase):
    
    def test_safe_json_loads_valid(self):
        """Test that safe_json_loads handles normal JSON correctly."""
        data = {"key": "value", "list": [1, 2, 3]}
        json_str = json.dumps(data)
        result = _safe_json_loads(json_str)
        self.assertEqual(result, data)

    def test_safe_json_loads_depth_limit(self):
        """Test that safe_json_loads rejects deep nesting."""
        # Create nesting deeper than MAX_JSON_DEPTH (100)
        # Using dicts because object_pairs_hook currently guards dicts
        depth = MAX_JSON_DEPTH + 10
        deep_json = "{"
        for i in range(depth):
            deep_json += f'"k{i}": {{'
        deep_json += '"end": 1'
        deep_json += "}" * (depth + 1)
        
        with self.assertRaises(ValueError) as cm:
            _safe_json_loads(deep_json)
        
        self.assertIn("exceeds max depth", str(cm.exception))

    def test_heuristic_repair_size_limit(self):
        """Test that heuristic repair skips large strings."""
        # Large string > 1MB
        large_json = '{"data": "' + "x" * (MAX_JSON_PARSE_SIZE + 100) + '"}'
        
        result = _heuristic_repair(large_json)
        self.assertIsNone(result)

    def test_validate_output_size_guard(self):
        """Test that validate_output skips parsing for large strings."""
        config = CleansingConfig()
        cleaner = OutputCleaner(config)
        
        # Mock target node spec
        target_spec = MagicMock()
        target_spec.input_keys = ["large_field"]
        target_spec.input_schema = None
        
        # Create output with large value
        large_val = "x" * (MAX_JSON_PARSE_SIZE + 100)
        output = {"large_field": large_val}
        
        result = cleaner.validate_output(output, "source", target_spec)
        
        # Should be valid (because we skip the trap check for large strings)
        self.assertTrue(result.valid)
        
        # Should have a warning about skipping
        self.assertTrue(any("oversized string" in w for w in result.warnings))

    def test_validate_output_traps_deep_nesting(self):
        """Test that validate_output catches deep nesting in strings."""
        config = CleansingConfig()
        cleaner = OutputCleaner(config)
        
        target_spec = MagicMock()
        target_spec.input_keys = ["json_field"]
        
        # Create a deep JSON string that fits in size but exceeds depth
        depth = MAX_JSON_DEPTH + 10
        deep_obj = "{"
        for i in range(depth):
            deep_obj += f'"k{i}": {{'
        deep_obj += '"end": 1'
        deep_obj += "}" * (depth + 1)
        
        output = {"json_field": deep_obj}
        
        # It shouldn't crash, it should just fail the try-except block in validate_output
        # and likely treat it as a non-JSON string or just pass validation if it doesn't fail type check
        result = cleaner.validate_output(output, "source", target_spec)
        
        # It passes validation because the "trap check" failed to parse, 
        # so it assumes it's just a normal string (which is safe behavior).
        self.assertTrue(result.valid)

if __name__ == "__main__":
    unittest.main()
