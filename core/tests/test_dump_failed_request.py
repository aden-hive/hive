"""Tests for _dump_failed_request graceful error handling.

Covers Issue #5965: _dump_failed_request crashes agent on read-only filesystems.
The fix wraps file I/O in try/except so the agent continues running even when
debug dumps cannot be written (read-only FS, disk full, permission denied).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _skip_without_litellm():
    """Skip the entire module if litellm is not installed."""
    pytest.importorskip("litellm")


class TestDumpFailedRequest:
    """Verify _dump_failed_request never raises on I/O failures."""

    def _get_fn(self):
        from framework.llm.litellm import _dump_failed_request

        return _dump_failed_request

    def test_returns_path_on_success(self, tmp_path):
        """Normal case: file is written and path is returned."""
        dump = self._get_fn()
        with patch("framework.llm.litellm.FAILED_REQUESTS_DIR", tmp_path):
            result = dump(
                model="gpt-4",
                kwargs={"messages": [{"role": "user", "content": "hi"}]},
                error_type="rate_limit",
                attempt=0,
            )
        assert tmp_path.as_posix() in result or str(tmp_path) in result
        # A .json file should have been created
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1

    def test_readonly_mkdir_fails(self, tmp_path):
        """When mkdir raises (read-only FS), return a fallback string instead of crashing."""
        dump = self._get_fn()
        fake_dir = tmp_path / "nonexistent" / "deep"
        mkdir_err = OSError("Read-only file system")
        with patch("framework.llm.litellm.FAILED_REQUESTS_DIR", fake_dir):
            with patch.object(type(fake_dir), "mkdir", side_effect=mkdir_err):
                result = dump(
                    model="gpt-4",
                    kwargs={"messages": []},
                    error_type="empty_response",
                    attempt=1,
                )
        assert "<unavailable" in result

    def test_write_permission_denied(self, tmp_path):
        """When open() raises PermissionError, return fallback instead of crashing."""
        dump = self._get_fn()
        with patch("framework.llm.litellm.FAILED_REQUESTS_DIR", tmp_path):
            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                result = dump(
                    model="claude-3",
                    kwargs={"messages": [{"role": "user", "content": "test"}]},
                    error_type="rate_limit",
                    attempt=2,
                )
        assert "<unavailable" in result

    def test_disk_full(self, tmp_path):
        """When open() raises OSError (disk full), return fallback."""
        dump = self._get_fn()
        with patch("framework.llm.litellm.FAILED_REQUESTS_DIR", tmp_path):
            with patch("builtins.open", side_effect=OSError("No space left on device")):
                result = dump(
                    model="gpt-4o",
                    kwargs={"messages": []},
                    error_type="empty_response",
                    attempt=0,
                )
        assert "<unavailable" in result
