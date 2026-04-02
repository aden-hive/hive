"""Tests for security.py - get_sandboxed_path() function."""

from unittest.mock import patch

import pytest


class TestGetSandboxedPath:
    """Tests for get_sandboxed_path() function."""

    @pytest.fixture(autouse=True)
    def setup_sandboxes_dir(self, tmp_path):
        """Patch AGENT_SANDBOXES_DIR to use temp directory."""
        self.sandboxes_dir = tmp_path / "sandboxes" / "default"
        self.sandboxes_dir.mkdir(parents=True)
        with patch(
            "aden_tools.tools.file_system_toolkits.security.AGENT_SANDBOXES_DIR",
            str(self.sandboxes_dir),
        ):
            yield

    @pytest.fixture
    def agent_id(self):
        """Standard agent ID."""
        return {"agent_id": "test-agent"}

    def test_creates_agent_directory(self, agent_id):
        """Agent directory is created if it doesn't exist."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        get_sandboxed_path("file.txt", agent_id=agent_id["agent_id"])

        agent_dir = self.sandboxes_dir / "test-agent" / "current"
        assert agent_dir.exists()
        assert agent_dir.is_dir()

    def test_relative_path_resolved(self, agent_id):
        """Relative paths are resolved within agent directory."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("subdir/file.txt", agent_id=agent_id["agent_id"])

        expected = (
            self.sandboxes_dir
            / "test-agent"
            / "current"
            / "subdir"
            / "file.txt"
        )
        assert result == str(expected)

    def test_absolute_path_treated_as_relative(self, agent_id):
        """Absolute paths are treated as relative to agent root."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("/etc/passwd", agent_id=agent_id["agent_id"])

        expected = (
            self.sandboxes_dir
            / "test-agent"
            / "current"
            / "etc"
            / "passwd"
        )
        assert result == str(expected)

    def test_path_traversal_blocked(self, agent_id):
        """Path traversal attempts are blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        with pytest.raises(ValueError, match="outside the agent sandbox"):
            get_sandboxed_path("../../../etc/passwd", agent_id=agent_id["agent_id"])

    def test_path_traversal_with_nested_dotdot(self, agent_id):
        """Nested path traversal with valid prefix is blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        with pytest.raises(ValueError, match="outside the agent sandbox"):
            get_sandboxed_path("valid/../../..", agent_id=agent_id["agent_id"])

    def test_path_traversal_absolute_with_dotdot(self, agent_id):
        """Absolute path with traversal is blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        with pytest.raises(ValueError, match="outside the agent sandbox"):
            get_sandboxed_path("/foo/../../../etc/passwd", agent_id=agent_id["agent_id"])

    def test_missing_agent_id_raises(self, agent_id):
        """Missing agent_id raises ValueError."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        with pytest.raises(ValueError, match="agent_id.*required"):
            get_sandboxed_path("file.txt", agent_id="")

    def test_none_agent_id_raises(self, agent_id):
        """None value for agent_id raises ValueError."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        with pytest.raises(ValueError):
            get_sandboxed_path("file.txt", agent_id=None)

    def test_simple_filename(self, agent_id):
        """Simple filename resolves correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("file.txt", agent_id=agent_id["agent_id"])

        expected = self.sandboxes_dir / "test-agent" / "current" / "file.txt"
        assert result == str(expected)

    def test_current_dir_path(self, agent_id):
        """Current directory path (.) resolves to agent dir."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path(".", agent_id=agent_id["agent_id"])

        expected = self.sandboxes_dir / "test-agent" / "current"
        assert result == str(expected)

    def test_dot_slash_path(self, agent_id):
        """Dot-slash paths resolve correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("./subdir/file.txt", agent_id=agent_id["agent_id"])

        expected = (
            self.sandboxes_dir
            / "test-agent"
            / "current"
            / "subdir"
            / "file.txt"
        )
        assert result == str(expected)

    def test_deeply_nested_path(self, agent_id):
        """Deeply nested paths work correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("a/b/c/d/e/file.txt", agent_id=agent_id["agent_id"])

        expected = (
            self.sandboxes_dir
            / "test-agent"
            / "current"
            / "a"
            / "b"
            / "c"
            / "d"
            / "e"
            / "file.txt"
        )
        assert result == str(expected)

    def test_path_with_spaces(self, agent_id):
        """Paths with spaces work correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("my folder/my file.txt", agent_id=agent_id["agent_id"])

        expected = (
            self.sandboxes_dir
            / "test-agent"
            / "current"
            / "my folder"
            / "my file.txt"
        )
        assert result == str(expected)

    def test_path_with_special_characters(self, agent_id):
        """Paths with special characters work correctly."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("file-name_v2.0.txt", agent_id=agent_id["agent_id"])

        expected = (
            self.sandboxes_dir
            / "test-agent"
            / "current"
            / "file-name_v2.0.txt"
        )
        assert result == str(expected)

    def test_empty_path(self, agent_id):
        """Empty string path resolves to agent directory."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        result = get_sandboxed_path("", agent_id=agent_id["agent_id"])

        expected = self.sandboxes_dir / "test-agent" / "current"
        assert result == str(expected)

    def test_symlink_within_sandbox_works(self, agent_id):
        """Symlinks that stay within sandbox are allowed."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        # Create agent directory structure
        agent_dir = self.sandboxes_dir / "test-agent" / "current"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create a target file and a symlink to it
        target_file = agent_dir / "target.txt"
        target_file.write_text("content", encoding="utf-8")
        symlink_path = agent_dir / "link_to_target"
        symlink_path.symlink_to(target_file)

        # Path through symlink should resolve to real target path
        result = get_sandboxed_path("link_to_target", agent_id=agent_id["agent_id"])

        # realpath resolves to symlink, so result points to real file
        assert result == str(target_file.resolve())

    def test_symlink_escape_blocked(self, agent_id):
        """Symlinks pointing outside sandbox are blocked by get_sandboxed_path."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        # Create agent directory
        agent_dir = self.sandboxes_dir / "test-agent" / "current"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create a symlink inside agent pointing outside
        outside_target = self.sandboxes_dir / "outside_file.txt"
        outside_target.write_text("sensitive data", encoding="utf-8")
        symlink_path = agent_dir / "escape_link"
        symlink_path.symlink_to(outside_target)

        # get_sandboxed_path resolves symlinks and blocks escape
        with pytest.raises(ValueError, match="outside the agent sandbox"):
            get_sandboxed_path("escape_link", agent_id=agent_id["agent_id"])

    def test_symlink_to_root_escape_blocked(self, agent_id):
        """Symlink to / inside sandbox then traversing through it is blocked."""
        from aden_tools.tools.file_system_toolkits.security import get_sandboxed_path

        # Create agent directory
        agent_dir = self.sandboxes_dir / "test-agent" / "current"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create a symlink to root filesystem inside sandbox
        symlink_path = agent_dir / "root"
        symlink_path.symlink_to("/")

        # Attempting to access files through symlink should be blocked
        with pytest.raises(ValueError, match="outside the agent sandbox"):
            get_sandboxed_path("root/etc/passwd", agent_id=agent_id["agent_id"])
