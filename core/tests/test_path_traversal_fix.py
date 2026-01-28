"""
Tests for path traversal vulnerability fix in FileStorage.

Verifies that the _validate_key() method properly blocks path traversal attempts.
"""

import pytest
from pathlib import Path
import tempfile

from framework.storage.backend import FileStorage


class TestPathTraversalProtection:
    """Tests for path traversal vulnerability protection."""

    @pytest.fixture
    def storage(self):
        """Create a temporary storage instance for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FileStorage(tmpdir)

    # === VALID KEYS (should pass validation) ===

    def test_valid_alphanumeric_key(self, storage):
        """Alphanumeric keys should be allowed."""
        # Should not raise
        storage._validate_key("goal_123")
        storage._validate_key("run_abc_def")
        storage._validate_key("status_completed")

    def test_valid_key_with_hyphens_underscores(self, storage):
        """Keys with hyphens and underscores should be allowed."""
        storage._validate_key("goal-123")
        storage._validate_key("run_id_456")
        storage._validate_key("completed-nodes_list")

    # === PATH TRAVERSAL ATTEMPTS (should raise ValueError) ===

    def test_blocks_parent_directory_traversal(self, storage):
        """Block .. path traversal attempts."""
        # These all have path separators which are blocked first
        with pytest.raises(ValueError):
            storage._validate_key("../../../etc/passwd")

        with pytest.raises(ValueError):
            storage._validate_key("..\\..\\windows\\system32")

        with pytest.raises(ValueError):
            storage._validate_key("goal/../../../.env")

    def test_blocks_leading_dot(self, storage):
        """Block keys starting with dot."""
        with pytest.raises(ValueError, match="path traversal detected"):
            storage._validate_key(".env")

        # This also has path separator which is caught first
        with pytest.raises(ValueError):
            storage._validate_key(".ssh/id_rsa")

    def test_blocks_absolute_paths_unix(self, storage):
        """Block absolute paths (Unix)."""
        # These have path separators which are blocked first
        with pytest.raises(ValueError):
            storage._validate_key("/etc/passwd")

        with pytest.raises(ValueError):
            storage._validate_key("/var/www/html/shell.php")

    def test_blocks_absolute_paths_windows(self, storage):
        """Block absolute paths (Windows)."""
        # These have path separators which are blocked first
        with pytest.raises(ValueError):
            storage._validate_key("C:\\Windows\\System32")

        with pytest.raises(ValueError):
            storage._validate_key("D:\\config\\database.yaml")

    def test_blocks_path_separators(self, storage):
        """Block forward and backward slashes."""
        with pytest.raises(ValueError, match="path separators not allowed"):
            storage._validate_key("goal/subdir/id")

        with pytest.raises(ValueError, match="path separators not allowed"):
            storage._validate_key("goal\\subdir\\id")

        with pytest.raises(ValueError, match="path separators not allowed"):
            storage._validate_key("some/path/to/../../.env")

    def test_blocks_null_bytes(self, storage):
        """Block null byte injection."""
        with pytest.raises(ValueError, match="null bytes not allowed"):
            storage._validate_key("goal\x00passwd")

    def test_blocks_dangerous_shell_chars(self, storage):
        """Block dangerous shell characters."""
        with pytest.raises(ValueError, match="dangerous characters"):
            storage._validate_key("goal`whoami`")

        with pytest.raises(ValueError, match="dangerous characters"):
            storage._validate_key("goal$(cat)")

        with pytest.raises(ValueError, match="dangerous characters"):
            storage._validate_key("goal|nc")

        with pytest.raises(ValueError, match="dangerous characters"):
            storage._validate_key("goal&& rm")

    def test_blocks_empty_key(self, storage):
        """Block empty keys."""
        with pytest.raises(ValueError, match="empty"):
            storage._validate_key("")

        with pytest.raises(ValueError, match="empty"):
            storage._validate_key("   ")

    # === END-TO-END TESTS ===

    def test_get_runs_by_goal_blocks_traversal(self, storage):
        """get_runs_by_goal() should block path traversal."""
        with pytest.raises(ValueError):
            storage.get_runs_by_goal("../../../.env")

    def test_get_runs_by_node_blocks_traversal(self, storage):
        """get_runs_by_node() should block path traversal."""
        with pytest.raises(ValueError):
            storage.get_runs_by_node("/etc/passwd")

    def test_get_runs_by_status_blocks_traversal(self, storage):
        """get_runs_by_status() should block path traversal."""
        with pytest.raises(ValueError):
            storage.get_runs_by_status("..\\..\\windows\\system32")

    def test_valid_queries_still_work(self, storage):
        """Valid queries should work after fix."""
        # These should return empty list, not raise errors
        result = storage.get_runs_by_goal("legitimate_goal")
        assert result == []

        result = storage.get_runs_by_node("legitimate_node")
        assert result == []

        result = storage.get_runs_by_status("completed")
        assert result == []

    # === REAL-WORLD ATTACK SCENARIOS ===

    def test_blocks_env_file_escape(self, storage):
        """Block attempts to access .env files."""
        with pytest.raises(ValueError):
            storage.get_runs_by_goal("../../../.env")

    def test_blocks_config_file_escape(self, storage):
        """Block attempts to access config files."""
        with pytest.raises(ValueError):
            storage.get_runs_by_goal("../../../../etc/aden/database.yaml")

    def test_blocks_web_shell_creation(self, storage):
        """Block attempts to create web shells."""
        with pytest.raises(ValueError):
            storage._add_to_index("by_goal", "../../var/www/html/shell", "malicious_code")

    def test_blocks_cron_injection(self, storage):
        """Block attempts to create cron jobs."""
        with pytest.raises(ValueError):
            storage._add_to_index("by_node", "../../../etc/cron.d/backdoor", "reverse_shell")

    def test_blocks_sudoers_modification(self, storage):
        """Block attempts to modify sudoers file."""
        with pytest.raises(ValueError):
            storage._add_to_index("by_status", "../../../../etc/sudoers", "ALL=(ALL) NOPASSWD:ALL")


class TestPathTraversalWithActualFiles:
    """Test path traversal protection with actual file operations."""

    def test_cannot_escape_storage_directory(self):
        """Verify that even with path traversal, we can't escape storage dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_dir = tmpdir_path / "storage"
            storage_dir.mkdir()

            # Create a secret file outside storage
            secret_file = tmpdir_path / "secret.txt"
            secret_file.write_text("SENSITIVE_DATA")

            storage = FileStorage(storage_dir)

            # Attempt to read the secret file via path traversal
            with pytest.raises(ValueError):
                storage.get_runs_by_goal("../secret")

            # Verify the secret file was not accessed (still contains original data)
            assert secret_file.read_text() == "SENSITIVE_DATA"

    def test_cannot_write_outside_storage(self):
        """Verify that we can't write files outside storage directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_dir = tmpdir_path / "storage"
            storage_dir.mkdir()

            storage = FileStorage(storage_dir)

            # Attempt to write outside storage directory
            with pytest.raises(ValueError):
                storage._add_to_index("by_goal", "../../malicious", "payload")

            # Verify no file was created outside storage
            malicious_file = tmpdir_path / "malicious.json"
            assert not malicious_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
