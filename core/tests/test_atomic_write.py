"""Tests for atomic_write retry logic on Windows sharing violations."""

from pathlib import Path
from unittest.mock import patch

import pytest

from framework.utils.io import _replace_with_retry, atomic_write


class TestAtomicWriteBasic:
    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        with atomic_write(target) as f:
            f.write("hello")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_creates_binary_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        with atomic_write(target, mode="wb") as f:
            f.write(b"\x00\x01\x02")
        assert target.read_bytes() == b"\x00\x01\x02"

    def test_temp_removed_on_exception(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        with pytest.raises(RuntimeError):
            with atomic_write(target) as f:
                f.write("partial")
                raise RuntimeError("boom")
        assert not target.exists()
        leftovers = list(tmp_path.glob(".test.txt.*.tmp"))
        assert leftovers == []

    def test_existing_file_replaced(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("old", encoding="utf-8")
        with atomic_write(target) as f:
            f.write("new")
        assert target.read_text(encoding="utf-8") == "new"


class TestReplaceWithRetry:
    def test_succeeds_without_error(self, tmp_path: Path) -> None:
        src = tmp_path / "a.tmp"
        dst = tmp_path / "b.txt"
        src.write_text("data")
        dst.write_text("old")
        _replace_with_retry(src, dst)
        assert dst.read_text() == "data"
        assert not src.exists()

    def test_retries_on_permission_error(self, tmp_path: Path) -> None:
        src = tmp_path / "a.tmp"
        dst = tmp_path / "b.txt"
        src.write_text("new")
        dst.write_text("old")

        call_count = 0
        original_replace = Path.replace

        def mock_replace(self, target):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise PermissionError(13, "Access is denied")
            return original_replace(self, target)

        with patch("framework.utils.io.sys") as mock_sys:
            mock_sys.platform = "win32"
            with patch.object(Path, "replace", mock_replace):
                _replace_with_retry(src, dst)

        assert call_count == 3
        assert dst.read_text() == "new"

    def test_raises_after_max_retries(self, tmp_path: Path) -> None:
        src = tmp_path / "a.tmp"
        dst = tmp_path / "b.txt"
        src.write_text("new")
        dst.write_text("old")

        def always_fails(self, target):
            raise PermissionError(13, "Access is denied")

        with patch("framework.utils.io.sys") as mock_sys:
            mock_sys.platform = "win32"
            with patch.object(Path, "replace", always_fails):
                with pytest.raises(PermissionError):
                    _replace_with_retry(src, dst)

    def test_no_retry_on_posix(self, tmp_path: Path) -> None:
        src = tmp_path / "a.tmp"
        dst = tmp_path / "b.txt"
        src.write_text("data")

        with patch("framework.utils.io.sys") as mock_sys:
            mock_sys.platform = "linux"

            def always_fails(self, target):
                raise PermissionError(13, "Access is denied")

            with patch.object(Path, "replace", always_fails):
                with pytest.raises(PermissionError):
                    _replace_with_retry(src, dst)


class TestAtomicWriteIntegration:
    def test_atomic_write_survives_concurrent_reader(self, tmp_path: Path) -> None:
        """Simulate the exact Windows scenario from the issue."""
        target = tmp_path / "checkpoint.json"
        target.write_text("original", encoding="utf-8")

        reader = open(target, encoding="utf-8")
        try:
            with atomic_write(target) as f:
                f.write("new content")
            assert target.read_text(encoding="utf-8") == "new content"
        finally:
            reader.close()
