"""
Smoke tests for the MCP server module.
"""

import json
import os
import threading
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _mcp_available() -> bool:
    """Check if MCP dependencies are installed."""
    try:
        import mcp  # noqa: F401
        from mcp.server import FastMCP  # noqa: F401

        return True
    except ImportError:
        return False


MCP_AVAILABLE = _mcp_available()
MCP_SKIP_REASON = "MCP dependencies not installed"


class TestMCPDependencies:
    """Tests for MCP dependency availability."""

    def test_mcp_package_available(self):
        """Test that the mcp package can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import mcp

        assert mcp is not None

    def test_fastmcp_available(self):
        """Test that FastMCP class is available from mcp server."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from mcp.server import FastMCP

        assert FastMCP is not None


class TestAgentBuilderServerModule:
    """Tests for the agent_builder_server module."""

    def test_module_importable(self):
        """Test that framework.mcp.agent_builder_server can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import framework.mcp.agent_builder_server as module

        assert module is not None

    def test_mcp_object_exported(self):
        """Test that the module exports the 'mcp' object (FastMCP instance)."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from mcp.server import FastMCP

        from framework.mcp.agent_builder_server import mcp

        assert mcp is not None
        assert isinstance(mcp, FastMCP)

    def test_mcp_server_name(self):
        """Test that the MCP server has the expected name."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import mcp

        assert mcp.name == "agent-builder"


class TestMCPPackageExports:
    """Tests for the framework.mcp package exports."""

    def test_package_importable(self):
        """Test that framework.mcp package can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import framework.mcp

        assert framework.mcp is not None

    def test_agent_builder_server_exported(self):
        """Test that agent_builder_server is exported from framework.mcp."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from mcp.server import FastMCP

        from framework.mcp import agent_builder_server

        assert agent_builder_server is not None
        assert isinstance(agent_builder_server.mcp, FastMCP)


class TestAtomicWriteFunctions:
    """Tests for atomic file write functions used in agent exports."""

    def test_atomic_write_text_basic(self):
        """Test that _atomic_write_text creates a file with correct content."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            content = "Hello, World!"

            _atomic_write_text(test_file, content)

            assert test_file.exists()
            assert test_file.read_text(encoding="utf-8") == content

    def test_atomic_write_text_creates_parent_dirs(self):
        """Test that _atomic_write_text creates parent directories if needed."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "nested" / "dir" / "test.txt"
            content = "Nested content"

            _atomic_write_text(test_file, content)

            assert test_file.exists()
            assert test_file.read_text(encoding="utf-8") == content

    def test_atomic_write_text_unicode(self):
        """Test that _atomic_write_text handles Unicode content correctly."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "unicode.txt"
            content = "Hello 你好 🚀 مرحبا"

            _atomic_write_text(test_file, content)

            assert test_file.exists()
            assert test_file.read_text(encoding="utf-8") == content

    def test_atomic_write_text_overwrites_existing(self):
        """Test that _atomic_write_text overwrites existing files."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "existing.txt"
            test_file.write_text("old content", encoding="utf-8")

            new_content = "new content"
            _atomic_write_text(test_file, new_content)

            assert test_file.read_text(encoding="utf-8") == new_content

    def test_atomic_write_text_no_partial_writes(self):
        """Test that _atomic_write_text doesn't leave partial content on error."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            original_content = "original content"
            test_file.write_text(original_content, encoding="utf-8")

            # Simulate an error during write by patching os.fsync to raise
            with patch("os.fsync", side_effect=OSError("Disk full")):
                with pytest.raises(OSError):
                    _atomic_write_text(test_file, "new content that should not appear")

            # Original file should be unchanged
            assert test_file.read_text(encoding="utf-8") == original_content

    def test_atomic_write_text_no_temp_file_left_on_success(self):
        """Test that no temporary files are left after successful write."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            test_file = tmpdir_path / "test.txt"

            _atomic_write_text(test_file, "content")

            # Only the target file should exist, no .tmp files
            files = list(tmpdir_path.iterdir())
            assert len(files) == 1
            assert files[0].name == "test.txt"

    def test_atomic_write_json_basic(self):
        """Test that _atomic_write_json creates a file with correct JSON."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_json

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.json"
            data = {"name": "test", "values": [1, 2, 3]}

            _atomic_write_json(test_file, data)

            assert test_file.exists()
            with open(test_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == data

    def test_atomic_write_json_with_indent(self):
        """Test that _atomic_write_json respects indent parameter."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_json

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.json"
            data = {"key": "value"}

            _atomic_write_json(test_file, data, indent=4)

            content = test_file.read_text(encoding="utf-8")
            # With indent=4, the JSON should have 4-space indentation
            assert '    "key"' in content

    def test_atomic_write_json_with_datetime(self):
        """Test that _atomic_write_json handles non-serializable types via default=str."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from datetime import datetime
        from framework.mcp.agent_builder_server import _atomic_write_json

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.json"
            now = datetime.now()
            data = {"timestamp": now, "name": "test"}

            _atomic_write_json(test_file, data)

            assert test_file.exists()
            content = test_file.read_text(encoding="utf-8")
            # datetime should be serialized as string
            assert str(now) in content

    def test_atomic_write_json_creates_parent_dirs(self):
        """Test that _atomic_write_json creates parent directories if needed."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_json

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "nested" / "dir" / "test.json"
            data = {"nested": True}

            _atomic_write_json(test_file, data)

            assert test_file.exists()
            with open(test_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == data

    def test_atomic_write_json_overwrites_existing(self):
        """Test that _atomic_write_json overwrites existing files."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_json

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "existing.json"
            test_file.write_text('{"old": "data"}', encoding="utf-8")

            new_data = {"new": "data"}
            _atomic_write_json(test_file, new_data)

            with open(test_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded == new_data

    @pytest.mark.skipif(os.name == "nt", reason="Windows file locking prevents concurrent atomic renames")
    def test_atomic_write_concurrent_safety(self):
        """Test that concurrent atomic writes don't corrupt the file.
        
        Note: This test is skipped on Windows because Windows has stricter
        file locking semantics that prevent concurrent atomic renames.
        On POSIX systems, rename() is guaranteed to be atomic.
        """
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "concurrent.txt"
            results = []
            num_threads = 10
            iterations = 20

            def writer(thread_id: int):
                for i in range(iterations):
                    content = f"thread-{thread_id}-iteration-{i}"
                    _atomic_write_text(test_file, content)
                    # Verify the file is always valid (not corrupted)
                    try:
                        read_content = test_file.read_text(encoding="utf-8")
                        # Content should match the pattern (any thread's content)
                        assert read_content.startswith("thread-")
                        results.append(True)
                    except Exception as e:
                        results.append(False)

            threads = [
                threading.Thread(target=writer, args=(i,))
                for i in range(num_threads)
            ]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All operations should have succeeded without corruption
            assert all(results)
            # Final file should contain valid content
            final_content = test_file.read_text(encoding="utf-8")
            assert final_content.startswith("thread-")

    def test_atomic_write_large_file(self):
        """Test that _atomic_write_text handles large files correctly."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import _atomic_write_text

        with TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "large.txt"
            # Create ~1MB of content
            content = "x" * (1024 * 1024)

            _atomic_write_text(test_file, content)

            assert test_file.exists()
            assert test_file.stat().st_size == len(content)
            assert test_file.read_text(encoding="utf-8") == content
>>>>>>> b13f1b6 (test: add comprehensive tests for atomic write functions)
