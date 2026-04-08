"""
Tests for path traversal vulnerability protection in ConcurrentStorage.

Verifies that the _validate_key() method properly blocks path traversal
attempts and that the public storage API enforces these checks end-to-end.
"""

from pathlib import Path
import tempfile

import pytest

from framework.storage.concurrent import ConcurrentStorage


class TestPathTraversalProtection:
    """Tests for path traversal vulnerability protection in ConcurrentStorage."""

    @pytest.fixture
    def storage(self):
        """Create a temporary ConcurrentStorage instance for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield ConcurrentStorage(tmpdir)

    # === VALID KEYS (should pass validation) ===

    def test_valid_alphanumeric_key(self, storage):
        """Alphanumeric keys should be allowed."""
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

        # Also has a path separator which is caught first
        with pytest.raises(ValueError):
            storage._validate_key(".ssh/id_rsa")

    def test_blocks_absolute_paths_unix(self, storage):
        """Block absolute paths (Unix)."""
        with pytest.raises(ValueError):
            storage._validate_key("/etc/passwd")

        with pytest.raises(ValueError):
            storage._validate_key("/var/www/html/shell.php")

    def test_blocks_absolute_paths_windows(self, storage):
        """Block absolute paths (Windows)."""
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

    # === END-TO-END TESTS (public API enforces validation) ===

    @pytest.mark.asyncio
    async def test_load_run_blocks_traversal(self, storage):
        """load_run() must reject path traversal in the run_id."""
        with pytest.raises(ValueError):
            await storage.load_run("../../../.env")

    @pytest.mark.asyncio
    async def test_load_run_valid_id_returns_none(self, storage):
        """A valid but nonexistent run_id returns None, not an error."""
        result = await storage.load_run("legitimate_run_id", use_cache=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_run_blocks_traversal(self, storage):
        """delete_run() must reject path traversal in the run_id."""
        with pytest.raises(ValueError):
            await storage.delete_run("../etc/passwd")

    @pytest.mark.asyncio
    async def test_load_summary_blocks_traversal(self, storage):
        """load_summary() must reject path traversal in the run_id."""
        with pytest.raises(ValueError):
            await storage.load_summary("../../../.env")

    def test_load_run_sync_blocks_traversal(self, storage):
        """load_run_sync() must reject path traversal in the run_id."""
        with pytest.raises(ValueError):
            storage.load_run_sync("../../../.env")

    def test_save_run_sync_blocks_traversal(self, storage):
        """save_run_sync() must reject path traversal in the run_id."""
        from framework.schemas.run import Run

        run = Run(id="../../../.env", goal_id="test", goal_description="", input_data={})
        with pytest.raises(ValueError):
            storage.save_run_sync(run)

    def test_load_run_sync_valid_id_returns_none(self, storage):
        """load_run_sync with a legitimate nonexistent ID returns None."""
        result = storage.load_run_sync("legitimate_run_id")
        assert result is None

    # === REAL-WORLD ATTACK SCENARIOS (end-to-end) ===

    def test_blocks_env_file_escape_via_load_sync(self, storage):
        """Block attempts to read .env files via load_run_sync."""
        with pytest.raises(ValueError):
            storage.load_run_sync("../../../.env")

    def test_blocks_config_file_escape_via_load_sync(self, storage):
        """Block attempts to access config files via load_run_sync."""
        with pytest.raises(ValueError):
            storage.load_run_sync("../../../../etc/aden/database.yaml")

    def test_blocks_arbitrary_write_via_save_sync(self, storage):
        """Block attempts to write arbitrary files via save_run_sync."""
        from framework.schemas.run import Run

        run = Run(id="../../var/www/html/shell", goal_id="test", goal_description="", input_data={})
        with pytest.raises(ValueError):
            storage.save_run_sync(run)


class TestPathTraversalWithActualFiles:
    """Test path traversal protection with actual file operations."""

    def test_cannot_escape_storage_directory(self):
        """Verify that path traversal is caught before any filesystem access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            storage_dir = tmpdir_path / "storage"
            storage_dir.mkdir()

            # Create a secret file outside storage
            secret_file = tmpdir_path / "secret.txt"
            secret_file.write_text("SENSITIVE_DATA", encoding="utf-8")

            storage = ConcurrentStorage(storage_dir)

            # Attempt to read the secret file via path traversal — must raise
            with pytest.raises(ValueError):
                storage.load_run_sync("../secret")

            # Verify the secret file was not accessed
            assert secret_file.read_text(encoding="utf-8") == "SENSITIVE_DATA"

    def test_save_and_load_roundtrip(self, tmp_path):
        """Verify save_run_sync/load_run_sync roundtrip works correctly."""
        from framework.schemas.run import Run, RunStatus

        storage = ConcurrentStorage(tmp_path)
        run = Run(
            id="run_test_123",
            goal_id="goal_abc",
            goal_description="Integration test",
            input_data={},
        )
        run.complete(RunStatus.COMPLETED, "done")

        storage.save_run_sync(run)

        loaded = storage.load_run_sync("run_test_123")
        assert loaded is not None
        assert loaded.id == "run_test_123"
        assert loaded.status == RunStatus.COMPLETED

        # Verify the file is at the expected path
        run_file = tmp_path / "runs" / "run_test_123.json"
        assert run_file.exists()


class TestSessionStorePathTraversal:
    """Path traversal protection in SessionStore.get_session_path()."""

    @pytest.fixture
    def store(self, tmp_path):
        from framework.storage.session_store import SessionStore

        return SessionStore(tmp_path)

    def test_valid_session_id(self, store):
        path = store.get_session_path("session_20260206_143022_abc12345")
        assert path.name == "session_20260206_143022_abc12345"

    def test_blocks_parent_traversal(self, store):
        with pytest.raises(ValueError, match="Invalid session ID"):
            store.get_session_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_delete_session_blocks_traversal(self, store):
        with pytest.raises(ValueError, match="Invalid session ID"):
            await store.delete_session("../../package")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
