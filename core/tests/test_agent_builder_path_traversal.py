import json
import unittest
from pathlib import Path
import tempfile
import os
import sys

# Add core to sys.path to allow imports
sys.path.insert(0, os.getcwd())

from framework.mcp.agent_builder_server import (
    _safe_path_segment, 
    _safe_export_path,
    delete_session,
    SESSIONS_DIR
)

class TestAgentBuilderPathTraversal(unittest.TestCase):
    """Tests for path traversal protection in agent_builder_server."""

    def test_safe_path_segment_valid(self):
        """Valid segments should be allowed."""
        self.assertEqual(_safe_path_segment("my_agent"), "my_agent")
        self.assertEqual(_safe_path_segment("build_123"), "build_123")
        self.assertEqual(_safe_path_segment("session-abc"), "session-abc")

    def test_safe_path_segment_invalid(self):
        """Invalid segments should raise ValueError."""
        with self.assertRaises(ValueError):
            _safe_path_segment("../etc/passwd")
        
        with self.assertRaises(ValueError):
            _safe_path_segment("sub/dir")
            
        with self.assertRaises(ValueError):
            _safe_path_segment("..")

        with self.assertRaises(ValueError):
            _safe_path_segment("")

    def test_safe_export_path_valid(self):
        """Valid export paths should be allowed and stay within exports/."""
        path = _safe_export_path("my_agent")
        self.assertEqual(path.name, "my_agent")
        self.assertIn("exports", str(path))
        
        path = _safe_export_path("group/my_agent")
        self.assertEqual(path.name, "my_agent")
        self.assertEqual(path.parent.name, "group")
        self.assertIn("exports", str(path))

    def test_safe_export_path_invalid(self):
        """Invalid export paths should raise ValueError."""
        # This SHOULD raise ValueError because it escapes exports/
        with self.assertRaises(ValueError):
            _safe_export_path("../../etc/passwd")
            
        # This should NOT necessarily raise ValueError if it just becomes exports/etc/passwd
        # unless we want to block all absolute-looking paths.
        # Given current implementation, it's safe.

    def test_delete_session_protection(self):
        """delete_session should block path traversal."""
        # Create a dummy file outside SESSIONS_DIR
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp_name = tmp_path.stem # Path without .json
            
        try:
            # Attempt to delete via path traversal
            traversal_id = f"../{tmp_name}"
            
            result_json = delete_session(traversal_id)
            result = json.loads(result_json)
            
            self.assertFalse(result["success"])
            self.assertIn("error", result)
            self.assertTrue(tmp_path.exists(), "File should NOT have been deleted!")
            
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

if __name__ == "__main__":
    unittest.main()
