"""Tests for security.py path resolution functions."""

import os
import pytest
from unittest.mock import patch
from aden_tools.tools.file_system_toolkits.security import resolve_safe_path

class TestResolveSafePath:
    @pytest.fixture(autouse=True)
    def setup_allowed_roots(self, tmp_path):
        self.tmp_dir = str(tmp_path.resolve())
        with patch("aden_tools.tools.file_system_toolkits.security._ALLOWED_ROOTS", (self.tmp_dir,)):
            yield

    def test_valid_path(self):
        valid_path = os.path.join(self.tmp_dir, "test.txt")
        result = resolve_safe_path(valid_path)
        assert result == valid_path

    def test_relative_path_rejected(self):
        # We assume CWD is not tmp_dir
        with pytest.raises(ValueError, match="Access denied"):
            resolve_safe_path("test.txt")

    def test_path_traversal_blocked(self):
        with pytest.raises(ValueError, match="Access denied"):
            resolve_safe_path(os.path.join(self.tmp_dir, "..", "outside.txt"))

    def test_empty_path(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            resolve_safe_path("   ")
