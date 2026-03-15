"""
Tests for Memory Management CLI

These tests verify that the memory management CLI commands work correctly
with various session scenarios.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from framework.memory.cli import (
    cmd_analyze_session,
    cmd_cleanup_session,
    cmd_inspect_session,
    cmd_list_sessions,
    format_size,
    get_session_store,
)


class TestMemoryCLI(unittest.TestCase):
    """Test cases for Memory CLI commands."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.sessions_dir = self.temp_dir / "sessions"
        self.sessions_dir.mkdir()

        # Create a mock session
        self.test_session_id = "test_session_123"
        self.session_dir = self.sessions_dir / self.test_session_id
        self.session_dir.mkdir()

        # Create state.json
        self.state_data = {
            "created_at": "2026-03-15T14:30:00Z",
            "updated_at": "2026-03-15T14:35:00Z",
            "status": "completed",
            "agent_id": "test_agent",
        }

        state_file = self.session_dir / "state.json"
        with open(state_file, "w") as f:
            json.dump(self.state_data, f)

        # Create conversations directory
        conv_dir = self.session_dir / "conversations"
        conv_dir.mkdir()

        conv_file = conv_dir / "conversation1.json"
        with open(conv_file, "w") as f:
            json.dump({"messages": [{"role": "user", "content": "Hello"}]}, f)

        # Create logs directory
        logs_dir = self.session_dir / "logs"
        logs_dir.mkdir()

        log_file = logs_dir / "summary.json"
        with open(log_file, "w") as f:
            json.dump({"summary": "Test session completed"}, f)

    def test_format_size(self):
        """Test the format_size function."""
        self.assertEqual(format_size(512), "512.0 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(1048576), "1.0 MB")
        self.assertEqual(format_size(1073741824), "1.0 GB")

    @patch("framework.memory.cli.Path.home")
    def test_get_session_store(self, mock_home):
        """Test getting session store."""
        mock_home.return_value = self.temp_dir / ".hive"
        store = get_session_store()
        self.assertEqual(store.base_path.name, "agents")

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_list_sessions_empty(self, mock_get_store):
        """Test listing sessions when none exist."""
        mock_store = MagicMock()
        mock_store.sessions_dir.exists.return_value = False
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.agent = None
        args.limit = 20

        with patch("builtins.print") as mock_print:
            cmd_list_sessions(args)
            mock_print.assert_any_call("No sessions found.")

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_list_sessions_with_data(self, mock_get_store):
        """Test listing sessions with actual data."""
        mock_store = MagicMock()
        mock_store.sessions_dir = self.sessions_dir
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.agent = None
        args.limit = 20

        with patch("builtins.print") as mock_print:
            cmd_list_sessions(args)
            # Should print session info
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("test_session_123" in call for call in calls))

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_inspect_session(self, mock_get_store):
        """Test inspecting a session."""
        mock_store = MagicMock()
        mock_store.base_path = self.sessions_dir
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.session_id = self.test_session_id
        args.type = "all"

        with patch("builtins.print") as mock_print:
            cmd_inspect_session(args)
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("Session State:" in call for call in calls))
            self.assertTrue(any("Conversations:" in call for call in calls))
            self.assertTrue(any("Logs:" in call for call in calls))

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_inspect_session_not_found(self, mock_get_store):
        """Test inspecting a non-existent session."""
        mock_store = MagicMock()
        mock_store.base_path = self.sessions_dir
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.session_id = "nonexistent_session"
        args.type = "all"

        with patch("builtins.print") as mock_print:
            cmd_inspect_session(args)
            mock_print.assert_any_call("Session nonexistent_session not found.")

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_cleanup_session_dry_run(self, mock_get_store):
        """Test cleaning up a session with dry run."""
        mock_store = MagicMock()
        mock_store.base_path = self.sessions_dir
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.session_id = self.test_session_id
        args.dry_run = True

        with patch("builtins.print") as mock_print:
            cmd_cleanup_session(args)
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("Dry run" in call for call in calls))
            self.assertTrue(any("would clean up" in call for call in calls))

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_analyze_session(self, mock_get_store):
        """Test analyzing a session."""
        mock_store = MagicMock()
        mock_store.base_path = self.sessions_dir
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.session_id = self.test_session_id
        args.summary = False

        with patch("builtins.print") as mock_print:
            cmd_analyze_session(args)
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("Memory Analysis:" in call for call in calls))
            self.assertTrue(any("Overall Statistics:" in call for call in calls))

    @patch("framework.memory.cli.get_session_store")
    def test_cmd_analyze_session_summary(self, mock_get_store):
        """Test analyzing a session with summary only."""
        mock_store = MagicMock()
        mock_store.base_path = self.sessions_dir
        mock_get_store.return_value = mock_store

        args = MagicMock()
        args.session_id = self.test_session_id
        args.summary = True

        with patch("builtins.print") as mock_print:
            cmd_analyze_session(args)
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("Total Files:" in call for call in calls))
            self.assertTrue(any("Total Size:" in call for call in calls))
            # Should not show detailed breakdown
            self.assertFalse(any("By Type:" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
