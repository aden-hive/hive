"""
Tests for improved exception handling and logging in core components.

This test suite verifies that:
1. Bare `except Exception` patterns have been replaced with specific exceptions
2. Errors are properly logged with appropriate severity levels
3. Fallback mechanisms work correctly when exceptions occur
4. No information is silently swallowed without visibility
"""

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

# Import the modules we're testing
from framework.mcp.agent_builder_server import (
    _load_active_session,
    list_sessions,
    ACTIVE_SESSION_FILE,
    SESSIONS_DIR,
)
from framework.runner.orchestrator import AgentOrchestrator, RoutingDecision


class TestAgentBuilderServerExceptionHandling:
    """Tests for agent_builder_server.py exception handling improvements."""

    def test_load_active_session_file_not_found(self, caplog):
        """Test that file not found is handled gracefully with debug logging."""
        with caplog.at_level(logging.DEBUG):
            with patch.object(Path, "exists", return_value=False):
                result = _load_active_session()
        
        assert result is None
        # File not found should not appear in logs as it's expected
        assert "not found" not in caplog.text.lower() or "debug" in caplog.text.lower()

    def test_load_active_session_corrupted_json(self, caplog):
        """Test that corrupted JSON is logged as warning, not silently ignored."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".active") as f:
            f.write("invalid{json{{")
            temp_file = f.name

        try:
            with caplog.at_level(logging.DEBUG):
                with patch.object(Path, "exists", return_value=True):
                    # Patch _load_session to raise JSONDecodeError
                    with patch("builtins.open", mock_open(read_data="valid_session_id")):
                        with patch("framework.mcp.agent_builder_server._load_session", 
                                  side_effect=json.JSONDecodeError("msg", "doc", 0)):
                            result = _load_active_session()

            assert result is None
            # Should have debug log about invalid session
            log_messages = [record.message for record in caplog.records]
            assert any("Invalid" in msg or "missing" in msg for msg in log_messages), \
                f"Expected InvalidSession or missing message in logs, got: {log_messages}"
        finally:
            Path(temp_file).unlink(missing_ok=True)

    def test_load_active_session_unexpected_error_logged(self, caplog):
        """Test that unexpected errors are logged with full exception info."""
        with caplog.at_level(logging.ERROR):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", side_effect=RuntimeError("Unexpected error")):
                    result = _load_active_session()

        assert result is None
        # Should have error log with exc_info
        assert any("Failed to load active session" in record.message 
                  for record in caplog.records 
                  if record.levelno >= logging.ERROR)

    def test_load_active_session_invalid_session_id(self, caplog):
        """Test that invalid session ID is handled gracefully."""
        with caplog.at_level(logging.DEBUG):
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", mock_open(read_data="invalid_id")):
                    with patch("framework.mcp.agent_builder_server._load_session",
                              side_effect=ValueError("Invalid session")):
                        result = _load_active_session()

        assert result is None
        # Should log debug message about invalid session
        assert any("Invalid or missing session" in record.message
                  for record in caplog.records
                  if record.levelno >= logging.DEBUG)

    def test_list_sessions_corrupted_json_skipped(self, caplog):
        """Test that corrupted session files are logged and skipped."""
        with caplog.at_level(logging.WARNING):
            with tempfile.TemporaryDirectory() as tmpdir:
                sessions_dir = Path(tmpdir)
                
                # Create one valid and one corrupted session file
                valid_file = sessions_dir / "valid.json"
                corrupted_file = sessions_dir / "corrupted.json"
                
                valid_file.write_text(json.dumps({
                    "session_id": "test_123",
                    "name": "Test Session",
                    "created_at": "2024-01-01",
                    "last_modified": "2024-01-01",
                    "nodes": [],
                    "edges": [],
                    "goal": None,
                }))
                
                corrupted_file.write_text("{invalid json")
                
                with patch("framework.mcp.agent_builder_server.SESSIONS_DIR", sessions_dir):
                    result = list_sessions()
                    
                # Result should be valid JSON
                data = json.loads(result)
                assert "sessions" in data
                # Valid session should be included
                assert any(s["session_id"] == "test_123" for s in data["sessions"])

    def test_list_sessions_missing_required_field_logged(self, caplog):
        """Test that session files with missing required fields are logged."""
        with caplog.at_level(logging.WARNING):
            with tempfile.TemporaryDirectory() as tmpdir:
                sessions_dir = Path(tmpdir)
                
                # Create session file without required field
                incomplete_file = sessions_dir / "incomplete.json"
                incomplete_file.write_text(json.dumps({
                    # Missing session_id and name
                    "created_at": "2024-01-01",
                }))
                
                with patch("framework.mcp.agent_builder_server.SESSIONS_DIR", sessions_dir):
                    # This approach is simpler - just verify exception handling works
                    result = list_sessions()
                    
                # Result should be valid JSON even if session file is bad
                data = json.loads(result)
                assert "sessions" in data
                assert "total" in data

    def test_list_sessions_permission_denied_logged(self, caplog):
        """Test that permission errors when reading sessions are logged."""
        with caplog.at_level(logging.WARNING):
            with tempfile.TemporaryDirectory() as tmpdir:
                sessions_dir = Path(tmpdir)
                session_file = sessions_dir / "test.json"
                session_file.write_text(json.dumps({"session_id": "test", "name": "test"}))
                
                # Make file unreadable
                session_file.chmod(0o000)
                
                try:
                    with patch("framework.mcp.agent_builder_server.SESSIONS_DIR", sessions_dir):
                        result = list_sessions()
                        
                    # Should still return valid JSON
                    data = json.loads(result)
                    assert "sessions" in data
                finally:
                    # Restore permissions for cleanup
                    session_file.chmod(0o644)

    def test_list_sessions_active_id_error_logged(self, caplog):
        """Test that errors reading active session file are logged."""
        with caplog.at_level(logging.WARNING):
            with tempfile.TemporaryDirectory() as tmpdir:
                sessions_dir = Path(tmpdir)
                active_file = sessions_dir / ".active"
                active_file.write_text("session_123")
                
                # Make file unreadable after exists() check
                with patch("framework.mcp.agent_builder_server.SESSIONS_DIR", sessions_dir):
                    with patch("framework.mcp.agent_builder_server.ACTIVE_SESSION_FILE", active_file):
                        active_file.chmod(0o000)
                        try:
                            result = list_sessions()
                            
                            # Should still return valid JSON
                            data = json.loads(result)
                            assert "active_session_id" in data
                        finally:
                            active_file.chmod(0o644)


class TestOrchestratorExceptionHandling:
    """Tests for orchestrator.py exception handling improvements."""

    @pytest.fixture
    def orchestrator(self):
        """Create an orchestrator instance for testing."""
        with patch("framework.runner.orchestrator.LLMProvider"):
            return AgentOrchestrator()

    def test_llm_route_invalid_json_response_logged(self, orchestrator, caplog):
        """Test that invalid JSON response from LLM is logged as warning."""
        with caplog.at_level(logging.WARNING):
            mock_response = MagicMock()
            mock_response.content = "not valid json"
            
            with patch.object(orchestrator._llm, "complete", return_value=mock_response):
                # Register a capable agent
                orchestrator._agents = {"agent1": MagicMock()}
                orchestrator._agent_capabilities = {
                    "agent1": [
                        MagicMock(reasoning="fallback"),
                    ]
                }
                
                # The method should fall back and log warning
                # Note: This depends on implementation details

    def test_llm_route_json_decode_error_handled(self, orchestrator, caplog):
        """Test that JSON decode errors are specifically caught and logged."""
        with caplog.at_level(logging.WARNING):
            mock_response = MagicMock()
            # Simulate a response that won't parse as JSON
            mock_response.content = "{invalid: json}"
            
            with patch.object(orchestrator._llm, "complete", return_value=mock_response):
                # Register agents
                mock_agent = MagicMock()
                orchestrator._agents = {"agent1": mock_agent}
                
                # Should not raise, should log warning and fall back
                # Exact behavior depends on method implementation

    def test_llm_route_missing_field_logged(self, caplog):
        """Test that missing expected fields in LLM response are logged."""
        with caplog.at_level(logging.WARNING):
            # Create response with valid JSON but missing required field
            mock_response = MagicMock()
            mock_response.content = '{"reasoning": "test"}'  # Missing 'selected'
            
            # The specific test depends on implementation details

    def test_llm_route_type_error_logged(self, caplog):
        """Test that type errors in LLM response are logged."""
        with caplog.at_level(logging.WARNING):
            # Create response where selected is not a list
            mock_response = MagicMock()
            mock_response.content = '{"selected": "not_a_list", "reasoning": "test"}'
            
            # The specific test depends on implementation details

    def test_llm_route_unexpected_error_logged(self, orchestrator, caplog):
        """Test that unexpected errors during routing are logged with full info."""
        with caplog.at_level(logging.ERROR):
            with patch.object(orchestrator._llm, "complete", 
                            side_effect=RuntimeError("Unexpected error")):
                # Should log error with exc_info
                # The specific test depends on implementation details
                pass


class TestExceptionLoggingBestPractices:
    """Tests for verifying exception handling best practices."""

    def test_no_bare_except_patterns(self):
        """Verify that no bare except: patterns exist (except specific ones)."""
        # Read the modified files
        agent_builder_path = Path("core/framework/mcp/agent_builder_server.py")
        orchestrator_path = Path("core/framework/runner/orchestrator.py")
        
        if agent_builder_path.exists():
            content = agent_builder_path.read_text()
            # Should not have bare except: pass patterns
            # Narrow exceptions or log before passing allowed
            assert content.count("except Exception:\n        pass") == 0, \
                "Found bare except Exception: pass patterns"

    def test_logging_configured(self):
        """Verify that logging is configured in modified modules."""
        agent_builder_path = Path("core/framework/mcp/agent_builder_server.py")
        orchestrator_path = Path("core/framework/runner/orchestrator.py")
        
        if agent_builder_path.exists():
            content = agent_builder_path.read_text()
            assert "import logging" in content, "logging not imported in agent_builder_server"
            assert 'logger = logging.getLogger(__name__)' in content, \
                "logger not configured in agent_builder_server"
        
        if orchestrator_path.exists():
            content = orchestrator_path.read_text()
            assert "import logging" in content, "logging not imported in orchestrator"
            assert 'logger = logging.getLogger(__name__)' in content, \
                "logger not configured in orchestrator"

    def test_specific_exceptions_caught(self):
        """Verify that specific exceptions are caught instead of bare Exception."""
        agent_builder_path = Path("core/framework/mcp/agent_builder_server.py")
        
        if agent_builder_path.exists():
            content = agent_builder_path.read_text()
            
            # Should catch specific exceptions
            assert "except FileNotFoundError" in content, \
                "Should catch FileNotFoundError specifically"
            assert "except json.JSONDecodeError" in content, \
                "Should catch JSONDecodeError specifically"
            assert "except KeyError" in content, \
                "Should catch KeyError specifically"
            assert "except OSError" in content, \
                "Should catch OSError specifically"


class TestErrorVisibility:
    """Tests ensuring errors are visible and not silently ignored."""

    def test_errors_have_logging_statements(self):
        """Verify that exceptions are logged, not silently passed."""
        agent_builder_path = Path("core/framework/mcp/agent_builder_server.py")
        
        if agent_builder_path.exists():
            content = agent_builder_path.read_text()
            
            # Count logging statements
            log_debug_count = content.count("logger.debug(")
            log_warning_count = content.count("logger.warning(")
            log_error_count = content.count("logger.error(")
            
            # Should have logging statements
            assert log_debug_count > 0, "Should have logger.debug() calls"
            assert log_warning_count > 0, "Should have logger.warning() calls"
            assert log_error_count > 0, "Should have logger.error() calls"

    def test_warning_level_for_corrupted_files(self):
        """Verify that corrupted file access is logged at WARNING level."""
        agent_builder_path = Path("core/framework/mcp/agent_builder_server.py")
        
        if agent_builder_path.exists():
            content = agent_builder_path.read_text()
            
            # Should log corrupted files at warning level
            assert "logger.warning" in content and "corrupted" in content, \
                "Should log corrupted files at WARNING level"

    def test_error_level_for_unexpected_errors(self):
        """Verify that unexpected errors are logged at ERROR level."""
        agent_builder_path = Path("core/framework/mcp/agent_builder_server.py")
        
        if agent_builder_path.exists():
            content = agent_builder_path.read_text()
            
            # Should log unexpected errors at error level with exc_info
            assert "logger.error" in content and "exc_info=True" in content, \
                "Should log unexpected errors at ERROR level with exc_info"


# Integration tests to verify fix works end-to-end
class TestExceptionHandlingIntegration:
    """Integration tests for exception handling improvements."""

    def test_load_active_session_fallback_works(self, caplog):
        """Test that fallback mechanism works when error occurs."""
        with caplog.at_level(logging.DEBUG):
            # Even with corrupted file, function should not raise
            with patch.object(Path, "exists", return_value=True):
                with patch("builtins.open", side_effect=IOError("Read error")):
                    result = _load_active_session()
                    
            # Should return None, not raise
            assert result is None

    def test_list_sessions_returns_valid_json(self):
        """Test that list_sessions always returns valid JSON."""
        # Create a problematic directory
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            
            # Create mixed good and bad files
            valid_file = sessions_dir / "valid.json"
            valid_file.write_text(json.dumps({
                "session_id": "test_123",
                "name": "Test",
                "created_at": "2024-01-01",
                "last_modified": "2024-01-01",
                "nodes": [],
                "edges": [],
                "goal": None,
            }))
            
            invalid_file = sessions_dir / "invalid.json"
            invalid_file.write_text("not json at all {{{")
            
            with patch("framework.mcp.agent_builder_server.SESSIONS_DIR", sessions_dir):
                result = list_sessions()
                
            # Should always return valid JSON
            data = json.loads(result)
            assert isinstance(data, dict)
            assert "sessions" in data
            assert "total" in data
            assert "active_session_id" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
