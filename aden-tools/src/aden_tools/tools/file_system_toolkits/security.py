import os
import pytest
import tempfile
import shutil

WORKSPACES_DIR = os.path.abspath(os.path.join(os.getcwd(), "workdir/workspaces"))

def get_secure_path(path: str, workspace_id: str, agent_id: str, session_id: str) -> str:
    """Resolve and verify a path within a 3-layer sandbox (workspace/agent/session)."""
    if not workspace_id or not agent_id or not session_id:
        raise ValueError("workspace_id, agent_id, and session_id are all required")

    # Ensure session directory exists: runtime/workspace_id/agent_id/session_id
    session_dir = os.path.join(WORKSPACES_DIR, workspace_id, agent_id, session_id)
    os.makedirs(session_dir, exist_ok=True)
    
    # Resolve absolute path
    if os.path.isabs(path):
        # Treat absolute paths as relative to the session root if they start with /
        rel_path = path.lstrip(os.sep)
        final_path = os.path.abspath(os.path.join(session_dir, rel_path))
    else:
        final_path = os.path.abspath(os.path.join(session_dir, path))
    
    # Verify path is within session_dir
    common_prefix = os.path.commonpath([final_path, session_dir])
    if common_prefix != session_dir:
        raise ValueError(f"Access denied: Path '{path}' is outside the session sandbox.")
        
    return final_path


class TestSecurePathResolution:
    """Test suite for secure path resolution with 3-layer sandboxing."""
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for each test."""
        # Setup: Create temp workspace directory
        self.original_workspaces_dir = globals()['WORKSPACES_DIR']
        self.temp_dir = tempfile.mkdtemp()
        globals()['WORKSPACES_DIR'] = self.temp_dir
        
        # Standard test IDs
        self.workspace_id = "ws123"
        self.agent_id = "agent456"
        self.session_id = "session789"
        
        yield
        
        # Teardown: Remove temp directory
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        globals()['WORKSPACES_DIR'] = self.original_workspaces_dir
    
    # == Path Traversal Attack Prevention ==
    
    def test_path_traversal_basic(self):
        """Test basic path traversal attack prevention."""
        malicious_path = "../../../etc/passwd"
        with pytest.raises(ValueError, match="Access denied.*outside the session sandbox"):
            get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
    
    def test_path_traversal_multiple_levels(self):
        """Test path traversal with many levels."""
        malicious_path = "../../../../../../../../etc/passwd"
        with pytest.raises(ValueError, match="Access denied.*outside the session sandbox"):
            get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
    
    def test_path_traversal_mixed_with_valid(self):
        """Test path traversal mixed with valid path components."""
        malicious_path = "data/../../../../../../etc/passwd"
        with pytest.raises(ValueError, match="Access denied.*outside the session sandbox"):
            get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
    
    def test_path_traversal_to_parent_workspace(self):
        """Test attempting to escape to parent workspace directory."""
        malicious_path = "../../../other_workspace/secret.txt"
        with pytest.raises(ValueError, match="Access denied.*outside the session sandbox"):
            get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
    
    def test_path_traversal_to_sibling_session(self):
        """Test attempting to access sibling session directory."""
        malicious_path = "../other_session/data.txt"
        with pytest.raises(ValueError, match="Access denied.*outside the session sandbox"):
            get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
    
    def test_path_traversal_encoded(self):
        """Test path traversal with URL-encoded components (should still fail)."""
        # Note: os.path.join doesn't decode, but this tests robustness
        malicious_path = "..%2F..%2F..%2Fetc%2Fpasswd"
        result = get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
        # Should be safely contained (treating encoded chars as literal)
        assert result.startswith(os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id))
    
    def test_path_traversal_with_symlink_attempt(self):
        """Test path that looks like symlink traversal."""
        malicious_path = "subdir/../../../../../../root/.ssh/id_rsa"
        with pytest.raises(ValueError, match="Access denied.*outside the session sandbox"):
            get_secure_path(malicious_path, self.workspace_id, self.agent_id, self.session_id)
    
    # == Absolute Path Handling ==
    
    def test_absolute_path_unix_style(self):
        """Test absolute path is treated as relative to session root."""
        abs_path = "/etc/config.json"
        result = get_secure_path(abs_path, self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, "etc/config.json")
        assert result == expected
    
    def test_absolute_path_with_subdirs(self):
        """Test absolute path with multiple subdirectories."""
        abs_path = "/data/logs/app.log"
        result = get_secure_path(abs_path, self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, "data/logs/app.log")
        assert result == expected
    
    def test_absolute_path_root_only(self):
        """Test absolute path that is just root."""
        abs_path = "/"
        result = get_secure_path(abs_path, self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        assert result == expected
    
    def test_absolute_path_multiple_slashes(self):
        """Test absolute path with multiple leading slashes."""
        abs_path = "///data//file.txt"
        result = get_secure_path(abs_path, self.workspace_id, self.agent_id, self.session_id)
        # Should normalize to session_dir/data/file.txt
        assert "data" in result
        assert result.startswith(os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id))
    
    # == Session Directory Creation ==
    
    def test_session_directory_created(self):
        """Test that session directory is created if it doesn't exist."""
        session_dir = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        assert not os.path.exists(session_dir)
        
        get_secure_path("test.txt", self.workspace_id, self.agent_id, self.session_id)
        
        assert os.path.exists(session_dir)
        assert os.path.isdir(session_dir)
    
    def test_session_directory_already_exists(self):
        """Test that existing session directory is not affected."""
        session_dir = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        os.makedirs(session_dir)
        
        # Create a file to verify directory isn't replaced
        test_file = os.path.join(session_dir, "existing.txt")
        with open(test_file, 'w') as f:
            f.write("test")
        
        get_secure_path("new.txt", self.workspace_id, self.agent_id, self.session_id)
        
        assert os.path.exists(test_file)
        assert os.path.isdir(session_dir)
    
    def test_nested_workspace_structure(self):
        """Test that full 3-layer structure is created."""
        session_dir = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        
        get_secure_path("file.txt", self.workspace_id, self.agent_id, self.session_id)
        
        # Verify all layers exist
        assert os.path.exists(os.path.join(self.temp_dir, self.workspace_id))
        assert os.path.exists(os.path.join(self.temp_dir, self.workspace_id, self.agent_id))
        assert os.path.exists(session_dir)
    
    # == Common Path Resolution ==
    
    def test_relative_path_simple(self):
        """Test simple relative path resolution."""
        result = get_secure_path("data.txt", self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, "data.txt")
        assert result == expected
    
    def test_relative_path_with_subdirs(self):
        """Test relative path with subdirectories."""
        result = get_secure_path("logs/app/debug.log", self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, "logs/app/debug.log")
        assert result == expected
    
    def test_relative_path_with_dot_current(self):
        """Test relative path with current directory reference."""
        result = get_secure_path("./data/file.txt", self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, "data/file.txt")
        assert result == expected
    
    def test_relative_path_with_dot_parent_safe(self):
        """Test relative path with parent reference that stays in sandbox."""
        result = get_secure_path("subdir/../file.txt", self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, "file.txt")
        assert result == expected
    
    def test_empty_path(self):
        """Test empty path resolves to session directory."""
        result = get_secure_path("", self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        assert result == expected
    
    def test_dot_path(self):
        """Test dot path resolves to session directory."""
        result = get_secure_path(".", self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        assert result == expected
    
    def test_common_prefix_calculation(self):
        """Test that common prefix is correctly calculated."""
        # Valid path should have session_dir as common prefix
        valid_path = "data/file.txt"
        result = get_secure_path(valid_path, self.workspace_id, self.agent_id, self.session_id)
        session_dir = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        
        assert os.path.commonpath([result, session_dir]) == session_dir
    
    # == Error Cases ==
    
    def test_missing_workspace_id(self):
        """Test error when workspace_id is missing."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", "", self.agent_id, self.session_id)
    
    def test_missing_agent_id(self):
        """Test error when agent_id is missing."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", self.workspace_id, "", self.session_id)
    
    def test_missing_session_id(self):
        """Test error when session_id is missing."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", self.workspace_id, self.agent_id, "")
    
    def test_none_workspace_id(self):
        """Test error when workspace_id is None."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", None, self.agent_id, self.session_id)
    
    def test_none_agent_id(self):
        """Test error when agent_id is None."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", self.workspace_id, None, self.session_id)
    
    def test_none_session_id(self):
        """Test error when session_id is None."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", self.workspace_id, self.agent_id, None)
    
    def test_all_ids_missing(self):
        """Test error when all IDs are missing."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", "", "", "")
    
    def test_whitespace_only_ids(self):
        """Test that whitespace-only IDs are treated as empty."""
        with pytest.raises(ValueError, match="workspace_id, agent_id, and session_id are all required"):
            get_secure_path("file.txt", "   ", self.agent_id, self.session_id)
    
    # == Edge Cases ==
    
    def test_special_characters_in_path(self):
        """Test path with special characters."""
        special_path = "data/file-name_v2.0.txt"
        result = get_secure_path(special_path, self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, special_path)
        assert result == expected
    
    def test_special_characters_in_ids(self):
        """Test IDs with special characters."""
        ws_id = "workspace-123_v2"
        ag_id = "agent.456"
        sess_id = "session_789-abc"
        
        result = get_secure_path("file.txt", ws_id, ag_id, sess_id)
        assert ws_id in result
        assert ag_id in result
        assert sess_id in result
    
    def test_very_long_path(self):
        """Test handling of very long paths."""
        long_path = "/".join([f"dir{i}" for i in range(50)]) + "/file.txt"
        result = get_secure_path(long_path, self.workspace_id, self.agent_id, self.session_id)
        session_dir = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id)
        assert result.startswith(session_dir)
    
    def test_unicode_path(self):
        """Test path with unicode characters."""
        unicode_path = "データ/ファイル.txt"
        result = get_secure_path(unicode_path, self.workspace_id, self.agent_id, self.session_id)
        expected = os.path.join(self.temp_dir, self.workspace_id, self.agent_id, self.session_id, unicode_path)
        assert result == expected
    
    def test_different_sessions_isolated(self):
        """Test that different sessions are properly isolated."""
        session1 = "session1"
        session2 = "session2"
        
        path1 = get_secure_path("data.txt", self.workspace_id, self.agent_id, session1)
        path2 = get_secure_path("data.txt", self.workspace_id, self.agent_id, session2)
        
        assert path1 != path2
        assert session1 in path1
        assert session2 in path2


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "--tb=short"])