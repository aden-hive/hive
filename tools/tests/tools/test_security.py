"""Tests for security.py - get_secure_path() function."""

import os
from unittest.mock import patch

import pytest


class TestGetSecurePath:
    """Tests for get_secure_path() function."""

    @pytest.fixture(autouse=True)
    def setup_workspaces_dir(self, tmp_path):
        """Patch WORKSPACES_DIR to use temp directory."""
        self.workspaces_dir = tmp_path / "workspaces"
        self.workspaces_dir.mkdir()
        with patch(
            "aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR",
            str(self.workspaces_dir),
        ):
            yield

    @pytest.fixture
    def ids(self):
        """Standard workspace, agent, and session IDs."""
        return {
            "workspace_id": "test-workspace",
            "agent_id": "test-agent",
            "session_id": "test-session",
        }

    def test_creates_session_directory(self, ids):
        """Session directory is created if it doesn't exist."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        get_secure_path("file.txt", **ids)  # Called for side effect (creates directory)

        session_dir = self.workspaces_dir / "test-workspace" / "test-agent" / "test-session"
        assert session_dir.exists()
        assert session_dir.is_dir()

    def test_relative_path_resolved(self, ids):
        """Relative paths are resolved within session directory."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("subdir/file.txt", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "subdir"
            / "file.txt"
        )
        assert result == str(expected)

    def test_absolute_path_treated_as_relative(self, ids):
        """Absolute paths are treated as relative to session root."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("/etc/passwd", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "etc"
            / "passwd"
        )
        assert result == str(expected)

    def test_path_traversal_blocked(self, ids):
        """Path traversal attempts are blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="outside the session sandbox"):
            get_secure_path("../../../etc/passwd", **ids)

    def test_path_traversal_with_nested_dotdot(self, ids):
        """Nested path traversal with valid prefix is blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="outside the session sandbox"):
            get_secure_path("valid/../../..", **ids)

    def test_path_traversal_absolute_with_dotdot(self, ids):
        """Absolute path with traversal is blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="outside the session sandbox"):
            get_secure_path("/foo/../../../etc/passwd", **ids)

    def test_missing_workspace_id_raises(self, ids):
        """Missing workspace_id raises ValueError."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="workspace_id.*required"):
            get_secure_path(
                "file.txt", workspace_id="", agent_id=ids["agent_id"], session_id=ids["session_id"]
            )

    def test_missing_agent_id_raises(self, ids):
        """Missing agent_id raises ValueError."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="agent_id.*required"):
            get_secure_path(
                "file.txt",
                workspace_id=ids["workspace_id"],
                agent_id="",
                session_id=ids["session_id"],
            )

    def test_missing_session_id_raises(self, ids):
        """Missing session_id raises ValueError."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="session_id.*required"):
            get_secure_path(
                "file.txt",
                workspace_id=ids["workspace_id"],
                agent_id=ids["agent_id"],
                session_id="",
            )

    def test_none_ids_raise(self):
        """None values for IDs raise ValueError."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError):
            get_secure_path("file.txt", workspace_id=None, agent_id="agent", session_id="session")

    def test_simple_filename(self, ids):
        """Simple filename resolves correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("file.txt", **ids)

        expected = (
            self.workspaces_dir / "test-workspace" / "test-agent" / "test-session" / "file.txt"
        )
        assert result == str(expected)

    def test_current_dir_path(self, ids):
        """Current directory path (.) resolves to session dir."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path(".", **ids)

        expected = self.workspaces_dir / "test-workspace" / "test-agent" / "test-session"
        assert result == str(expected)

    def test_dot_slash_path(self, ids):
        """Dot-slash paths resolve correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("./subdir/file.txt", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "subdir"
            / "file.txt"
        )
        assert result == str(expected)

    def test_deeply_nested_path(self, ids):
        """Deeply nested paths work correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("a/b/c/d/e/file.txt", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "a"
            / "b"
            / "c"
            / "d"
            / "e"
            / "file.txt"
        )
        assert result == str(expected)

    def test_path_with_spaces(self, ids):
        """Paths with spaces work correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("my folder/my file.txt", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "my folder"
            / "my file.txt"
        )
        assert result == str(expected)

    def test_path_with_special_characters(self, ids):
        """Paths with special characters work correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("file-name_v2.0.txt", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "file-name_v2.0.txt"
        )
        assert result == str(expected)

    def test_empty_path(self, ids):
        """Empty string path resolves to session directory."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("", **ids)

        expected = self.workspaces_dir / "test-workspace" / "test-agent" / "test-session"
        assert result == str(expected)

    def test_symlink_within_sandbox_works(self, ids):
        """Symlinks that stay within the sandbox are allowed."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        # Create session directory structure
        session_dir = self.workspaces_dir / "test-workspace" / "test-agent" / "test-session"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Create a target file and a symlink to it
        target_file = session_dir / "target.txt"
        target_file.write_text("content")
        symlink_path = session_dir / "link_to_target"
        symlink_path.symlink_to(target_file)

        # Path through symlink should resolve
        result = get_secure_path("link_to_target", **ids)

        assert result == str(symlink_path)

    def test_symlink_escape_detected_with_realpath(self, ids):
        """Symlinks pointing outside sandbox can be detected using realpath.

        Note: get_secure_path uses abspath (not realpath), so it validates the
        lexical path. To fully protect against symlink attacks, callers should
        verify realpath(result) is still within the sandbox before file I/O.
        This test documents that pattern.
        """
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        # Create session directory
        session_dir = self.workspaces_dir / "test-workspace" / "test-agent" / "test-session"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Create a symlink inside session pointing outside
        outside_target = self.workspaces_dir / "outside_file.txt"
        outside_target.write_text("sensitive data")
        symlink_path = session_dir / "escape_link"
        symlink_path.symlink_to(outside_target)

        # get_secure_path accepts the lexical path (symlink is inside session)
        result = get_secure_path("escape_link", **ids)
        assert result == str(symlink_path)

        # However, realpath reveals the escape - callers should check this
        real_path = os.path.realpath(result)
        assert os.path.commonpath([real_path, str(session_dir)]) != str(session_dir)

    # ========================================================================
    # Windows Path Security Tests (Path Traversal Vulnerability Fix)
    # ========================================================================

    def test_windows_absolute_path_with_forward_slash_blocked(self, ids):
        """Windows absolute paths with forward slashes are blocked (CVE fix)."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="drive letters are not allowed"):
            get_secure_path("C:/Windows/System32", **ids)

    def test_windows_absolute_path_with_backslash_blocked(self, ids):
        """Windows absolute paths with backslashes are blocked (CVE fix)."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="drive letters are not allowed"):
            get_secure_path("C:\\Windows\\System32", **ids)

    def test_different_drive_blocked(self, ids):
        """Paths on different drives are blocked (CVE fix)."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="drive letters are not allowed"):
            get_secure_path("D:/data/file.txt", **ids)

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "C:/Windows/System32/config/SAM",
            "D:/sensitive/data.txt",
            "C:\\Users\\Administrator\\.ssh\\id_rsa",
            "E:\\secrets.txt",
            "F:/Program Files/sensitive.dat",
            "Z:\\network\\share\\file.txt",
        ],
    )
    def test_all_windows_drive_letters_blocked(self, malicious_path, ids):
        """All Windows drive letters (A-Z) are blocked (CVE fix)."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="drive letters are not allowed"):
            get_secure_path(malicious_path, **ids)

    def test_windows_path_traversal_with_backslashes_blocked(self, ids):
        """Windows-style path traversal with backslashes is blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="outside the session sandbox"):
            get_secure_path("..\\..\\..\\Windows\\System32", **ids)

    def test_mixed_separators_normalized(self, ids):
        """Mixed path separators (/ and \\) are normalized correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("folder\\subfolder/file.txt", **ids)

        # Should contain both folder and subfolder
        assert "folder" in result and "subfolder" in result and "file.txt" in result
        # Should be within sandbox
        session_dir = str(self.workspaces_dir / "test-workspace" / "test-agent" / "test-session")
        assert result.startswith(session_dir)

    def test_multiple_leading_slashes_handled(self, ids):
        """Multiple leading slashes are handled correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("///etc/passwd", **ids)

        expected = (
            self.workspaces_dir
            / "test-workspace"
            / "test-agent"
            / "test-session"
            / "etc"
            / "passwd"
        )
        assert result == str(expected)

    def test_unc_path_blocked(self, ids):
        """UNC paths (\\\\server\\share) are blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        # UNC paths start with \\\\ which gets normalized
        # The double backslash at start should be stripped
        # But if it somehow forms a drive-like pattern, it should be blocked
        result = get_secure_path("\\\\server\\share\\file.txt", **ids)

        # Should be treated as relative path within sandbox
        session_dir = str(self.workspaces_dir / "test-workspace" / "test-agent" / "test-session")
        assert result.startswith(session_dir)

    def test_case_sensitivity_in_drive_detection(self, ids):
        """Drive letter detection is case-insensitive."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        # Lowercase drive letters should also be blocked
        with pytest.raises(ValueError, match="drive letters are not allowed"):
            get_secure_path("c:/windows/system32", **ids)

    def test_path_normalization_consistency(self, ids):
        """Equivalent paths normalize to the same result."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        path1 = get_secure_path("folder/file.txt", **ids)
        path2 = get_secure_path("folder\\file.txt", **ids)
        path3 = get_secure_path("./folder/file.txt", **ids)

        # All should resolve to the same normalized path
        assert os.path.normpath(path1) == os.path.normpath(path2)
        assert os.path.normpath(path1) == os.path.normpath(path3)

    def test_unicode_in_path_handled(self, ids):
        """Unicode characters in paths are handled correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        result = get_secure_path("folder/文件.txt", **ids)

        assert "folder" in result
        session_dir = str(self.workspaces_dir / "test-workspace" / "test-agent" / "test-session")
        assert result.startswith(session_dir)

    def test_long_path_handled(self, ids):
        """Very long paths are handled correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        long_path = "/".join(["folder"] * 50) + "/file.txt"
        result = get_secure_path(long_path, **ids)

        assert "folder" in result and "file.txt" in result
        session_dir = str(self.workspaces_dir / "test-workspace" / "test-agent" / "test-session")
        assert result.startswith(session_dir)

    @pytest.mark.parametrize(
        "traversal_path",
        [
            "../../../etc/passwd",
            "folder/../../../../../../etc/passwd",
            "..\\..\\..\\Windows\\System32",
            "folder\\..\\..\\..\\..\\Windows",
            "valid/../../../etc/passwd",
        ],
    )
    def test_various_traversal_attempts_blocked(self, traversal_path, ids):
        """Various path traversal attempts are blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_secure_path

        with pytest.raises(ValueError, match="outside the session sandbox"):
            get_secure_path(traversal_path, **ids)
