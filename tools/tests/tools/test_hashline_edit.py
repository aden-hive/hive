"""Integration tests for the hashline_edit tool."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.file_system_toolkits.hashline import compute_line_hash


@pytest.fixture
def mcp():
    """Create a FastMCP instance."""
    return FastMCP("test-server")


@pytest.fixture
def mock_workspace():
    """Mock workspace, agent, and session IDs."""
    return {
        "workspace_id": "test-workspace",
        "agent_id": "test-agent",
        "session_id": "test-session",
    }


@pytest.fixture
def mock_secure_path(tmp_path):
    """Mock get_secure_path to return temp directory paths."""

    def _get_secure_path(path, workspace_id, agent_id, session_id):
        return os.path.join(tmp_path, path)

    with patch(
        "aden_tools.tools.file_system_toolkits.hashline_edit.hashline_edit.get_secure_path",
        side_effect=_get_secure_path,
    ):
        yield


@pytest.fixture
def hashline_edit_fn(mcp):
    from aden_tools.tools.file_system_toolkits.hashline_edit import register_tools

    register_tools(mcp)
    return mcp._tool_manager._tools["hashline_edit"].fn


def _anchor(line_num, line_text):
    """Helper to build an anchor string."""
    return f"{line_num}:{compute_line_hash(line_text)}"


class TestSetLine:
    """Tests for the set_line op."""

    def test_set_line_basic(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """set_line replaces a single line."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert result["edits_applied"] == 1
        assert f.read_text() == "aaa\nBBB\nccc\n"

    def test_set_line_rejects_multiline_content(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """set_line with newlines in content returns error pointing to replace_lines."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "b1\nb2"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "single line" in result["error"]
        assert "replace_lines" in result["error"]
        # File must be unchanged
        assert f.read_text() == "aaa\nbbb\nccc\n"


class TestReplaceLines:
    """Tests for the replace_lines op."""

    def test_replace_lines_basic(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace_lines replaces a range of lines."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "NEW",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nNEW\nddd\n"

    def test_replace_lines_expand(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace_lines can expand a range into more lines."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(2, "bbb"),
                    "content": "x1\nx2\nx3",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nx1\nx2\nx3\nccc\n"

    def test_replace_lines_empty_content_deletes(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace_lines with content="" removes lines entirely (no blank line)."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nddd\n"


class TestInsertAfter:
    """Tests for the insert_after op."""

    def test_insert_after_basic(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """insert_after inserts new lines after the anchor line."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "insert_after", "anchor": _anchor(1, "aaa"), "content": "NEW"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nNEW\nbbb\nccc\n"

    def test_insert_after_multiline(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_after can insert multiple lines."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps(
            [{"op": "insert_after", "anchor": _anchor(1, "aaa"), "content": "x\ny\nz"}]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nx\ny\nz\nbbb\n"

    def test_multiple_insert_after_same_anchor_preserves_order(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Two insert_after at the same anchor produce A before B in output."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {"op": "insert_after", "anchor": _anchor(2, "bbb"), "content": "FIRST"},
                {"op": "insert_after", "anchor": _anchor(2, "bbb"), "content": "SECOND"},
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nbbb\nFIRST\nSECOND\nccc\n"

    def test_insert_after_newline_only_inserts_blank_line(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """A newline-only payload inserts one blank line."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps([{"op": "insert_after", "anchor": _anchor(1, "aaa"), "content": "\n"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert result["edits_applied"] == 1
        assert f.read_text() == "aaa\n\nbbb\n"


class TestReplace:
    """Tests for the replace (str_replace) op."""

    def test_replace_basic(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """replace does a string replacement."""
        f = tmp_path / "test.txt"
        f.write_text("hello world\ngoodbye world\n")

        edits = json.dumps(
            [{"op": "replace", "old_content": "hello world", "new_content": "hi world"}]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "hi world\ngoodbye world\n"


class TestBatchOps:
    """Tests for multiple operations in one call."""

    def test_batch_multiple_set_lines(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Multiple non-overlapping set_line ops in one batch."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"},
                {"op": "set_line", "anchor": _anchor(4, "ddd"), "content": "DDD"},
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert result["edits_applied"] == 2
        assert f.read_text() == "AAA\nbbb\nccc\nDDD\n"


class TestErrors:
    """Tests for error cases."""

    def test_invalid_json(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Invalid JSON returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")

        result = hashline_edit_fn(path="test.txt", edits="not json{", **mock_workspace)
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_hash_mismatch(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Stale hash returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")

        edits = json.dumps([{"op": "set_line", "anchor": "1:ffff", "content": "new"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "mismatch" in result["error"].lower()

    def test_line_out_of_range(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Line number beyond file length returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")

        edits = json.dumps([{"op": "set_line", "anchor": "99:ab12", "content": "new"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "out of range" in result["error"].lower()

    def test_overlapping_ranges(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Overlapping splice ranges are rejected."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "X",
                },
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(4, "ddd"),
                    "content": "Y",
                },
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "overlapping" in result["error"].lower()

    def test_replace_zero_matches(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace with zero matches returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")

        edits = json.dumps([{"op": "replace", "old_content": "nonexistent", "new_content": "new"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_replace_multiple_matches(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace with multiple matches returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello hello\n")

        edits = json.dumps([{"op": "replace", "old_content": "hello", "new_content": "hi"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "2 times" in result["error"]
        assert "anchor-based" in result["error"]

    def test_unknown_op(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Unknown op type returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")

        edits = json.dumps([{"op": "magic", "content": "x"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "unknown op" in result["error"].lower()

    def test_empty_edits_array(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Empty edits array returns error."""
        f = tmp_path / "test.txt"
        f.write_text("hello\n")

        result = hashline_edit_fn(path="test.txt", edits="[]", **mock_workspace)
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_insert_before_line1_overlaps_replace_at_line1(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_before line 1 + replace_lines starting at line 1 returns overlap error."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {"op": "insert_before", "anchor": _anchor(1, "aaa"), "content": "HEADER"},
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(2, "bbb"),
                    "content": "X",
                },
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "overlapping" in result["error"].lower()
        assert f.read_text() == "aaa\nbbb\nccc\n"

    def test_insert_inside_replace_range(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_after inside a replace_lines range is rejected as overlap."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "X",
                },
                {"op": "insert_after", "anchor": _anchor(2, "bbb"), "content": "NEW"},
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "overlapping" in result["error"].lower()
        # File must be unchanged (atomic)
        assert f.read_text() == "aaa\nbbb\nccc\nddd\n"

    def test_set_line_missing_content(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """set_line without content field returns error."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa")}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "missing" in result["error"].lower()
        assert "content" in result["error"].lower()
        # File must be unchanged
        assert f.read_text() == "aaa\nbbb\n"

    def test_replace_lines_missing_content(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace_lines without content field returns error."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(2, "bbb"),
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "missing" in result["error"].lower()
        assert "content" in result["error"].lower()
        # File must be unchanged
        assert f.read_text() == "aaa\nbbb\nccc\n"

    def test_set_line_empty_content_deletes(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """set_line with content="" deletes the line."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": ""}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "bbb\n"

    def test_file_not_found(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """Editing a non-existent file returns error."""
        edits = json.dumps([{"op": "set_line", "anchor": "1:0000", "content": "x"}])
        result = hashline_edit_fn(path="nope.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_replace_empty_old_content_returns_error(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace with old_content='' returns a clear error instead of confusing count."""
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")

        edits = json.dumps([{"op": "replace", "old_content": "", "new_content": "x"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "must not be empty" in result["error"]
        assert f.read_text() == "hello world\n"


class TestAtomicity:
    """Tests that no partial writes happen on validation failure."""

    def test_no_partial_apply_on_hash_mismatch(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """File is unchanged when one edit in a batch has a bad hash."""
        f = tmp_path / "test.txt"
        original = "aaa\nbbb\nccc\n"
        f.write_text(original)

        edits = json.dumps(
            [
                {"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"},
                {"op": "set_line", "anchor": "2:ffff", "content": "BBB"},  # bad hash
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert f.read_text() == original

    def test_no_partial_apply_on_overlap(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """File is unchanged when edits have overlapping ranges."""
        f = tmp_path / "test.txt"
        original = "aaa\nbbb\nccc\n"
        f.write_text(original)

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(2, "bbb"),
                    "content": "X",
                },
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "Y",
                },
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert f.read_text() == original


class TestReturnFormat:
    """Tests for the return value format."""

    def test_hashline_content_returned(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Returned content is in hashline format."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        # Content should have hashline format: N:hhhh|content
        lines = result["content"].split("\n")
        assert lines[0].startswith("1:")
        assert "|AAA" in lines[0]

    @pytest.mark.parametrize(
        "content,expected_ending",
        [("aaa\nbbb\n", True), ("aaa\nbbb", False)],
    )
    def test_trailing_newline_handling(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path, content, expected_ending
    ):
        """Trailing newline is preserved when present and absent when not."""
        f = tmp_path / "test.txt"
        f.write_text(content)

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
        hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert f.read_text().endswith("\n") == expected_ending

    def test_edits_applied_count(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """edits_applied reflects the number of ops."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"},
                {"op": "set_line", "anchor": _anchor(3, "ccc"), "content": "CCC"},
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["edits_applied"] == 2


class TestFix11HashlinePrefixStripping:
    """Fix 11: Strip hashline prefixes echoed in edit content."""

    def test_hashline_prefix_stripped_from_replace_lines(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Multi-line content with hashline prefixes is stripped."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        # Model echoes hashline prefixes on all lines
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "2:f1a2|BBB\n3:a2b3|CCC",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nBBB\nCCC\n"

    def test_hashline_prefix_not_stripped_when_not_all_match(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Lines without 100% hashline prefixes are kept as-is."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        # Only 1 of 3 lines has a prefix pattern (not 100%)
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "1:ab12|line1\nplain line\nanother plain",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "1:ab12|line1\nplain line\nanother plain\n"


class TestFix12EchoStripping:
    """Fix 12: Anchor echo stripping for insert_after and replace_lines."""

    def test_insert_after_strips_echoed_anchor_line(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Echoed first line matching anchor is removed, only new content inserted."""
        f = tmp_path / "test.txt"
        f.write_text("def hello():\n    pass\n")

        edits = json.dumps(
            [
                {
                    "op": "insert_after",
                    "anchor": _anchor(1, "def hello():"),
                    "content": "def hello():\n    # new comment",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "def hello():\n    # new comment\n    pass\n"

    def test_boundary_echo_not_stripped_when_only_one_side_matches(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Only leading boundary echoes; content should be left intact."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        # Content starts with "aaa" (echoes leading boundary) but does NOT end with "ddd"
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "aaa\nBBB\nCCC",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        # All three content lines kept (no stripping since only one boundary matches)
        assert f.read_text() == "aaa\naaa\nBBB\nCCC\nddd\n"

    def test_boundary_echo_not_stripped_when_no_content_between(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Both boundaries echo but only 2 content lines; no stripping (would delete)."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\naaa\n")

        # Content is ["aaa", "aaa"] -- both echo boundaries, but stripping both
        # would produce [] and delete line 2 entirely. Should keep content as-is.
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(2, "bbb"),
                    "content": "aaa\naaa",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\naaa\naaa\naaa\n"

    def test_insert_before_strips_echoed_trailing_anchor(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_before strips echoed anchor line from end of content."""
        f = tmp_path / "test.txt"
        f.write_text("def hello():\n    pass\n")

        edits = json.dumps(
            [
                {
                    "op": "insert_before",
                    "anchor": _anchor(2, "    pass"),
                    "content": "    # new comment\n    pass",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "def hello():\n    # new comment\n    pass\n"
        assert "insert_echo_strip" in result.get("cleanup_applied", [])

    def test_boundary_echo_stripped_when_content_equals_range_plus_two(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Both boundaries stripped even when content is exactly range_count + 2."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        # Replace 2 lines, content has 3 lines: boundary + 1 real + boundary
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "aaa\nX\nddd",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        # Both echoed boundaries stripped, only "X" remains as replacement
        assert f.read_text() == "aaa\nX\nddd\n"

    def test_replace_lines_strips_boundary_echo(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Echoed context lines before/after range are removed."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\nddd\n")

        # Model echoes surrounding context in the replacement
        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(2, "bbb"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "aaa\nBBB\nCCC\nddd",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nBBB\nCCC\nddd\n"


class TestFix13NoopDetection:
    """Fix 13: Unchanged edit detection reports edits_applied=0 with note."""

    def test_unchanged_edit_reports_zero_applied(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """set_line to same content returns edits_applied=0 with note."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "bbb"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert result["edits_applied"] == 0
        assert "note" in result
        assert "noop" not in result
        # File content unchanged
        assert f.read_text() == "aaa\nbbb\nccc\n"


def _resolve_anchor_placeholders(op, file_content):
    """Replace _anchor_N_text placeholders with real anchors based on file content."""
    resolved = dict(op)
    for key in ("anchor", "start_anchor", "end_anchor"):
        val = resolved.get(key, "")
        if isinstance(val, str) and val.startswith("_anchor_"):
            # Parse _anchor_N_text where N is 1-indexed line number
            parts = val.split("_", 3)  # ['', 'anchor', 'N', 'text']
            line_num = int(parts[2])
            line_text = parts[3] if len(parts) > 3 else ""
            resolved[key] = _anchor(line_num, line_text)
    return resolved


class TestFix14ContentTypeValidation:
    """Fix 14: Non-string content fields return clear error instead of crashing."""

    @pytest.mark.parametrize(
        "file_content,edit_op,label",
        [
            (
                "aaa\nbbb\n",
                {"op": "set_line", "anchor": "_anchor_1_aaa", "content": 42},
                "set_line int",
            ),
            (
                "hello world\n",
                {"op": "replace", "old_content": 42, "new_content": "x"},
                "replace old_content int",
            ),
            (
                "hello world\n",
                {"op": "replace", "old_content": "hello", "new_content": 99},
                "replace new_content int",
            ),
        ],
    )
    def test_non_string_content_returns_error(
        self,
        hashline_edit_fn,
        mock_workspace,
        mock_secure_path,
        tmp_path,
        file_content,
        edit_op,
        label,
    ):
        """Non-string content in any op returns a type error ({label})."""
        f = tmp_path / "test.txt"
        f.write_text(file_content)

        resolved_op = _resolve_anchor_placeholders(edit_op, file_content)
        edits = json.dumps([resolved_op])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result, f"[{label}] expected error"
        assert "string" in result["error"].lower(), f"[{label}] expected 'string' in error"


class TestFix16AutoCleanup:
    """Fix 16: Controllable auto-cleanup and cleanup metadata."""

    def test_auto_cleanup_true_strips_prefix(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Default behavior strips hashline prefixes and returns cleanup_applied."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "1:ab12|AAA\n2:cd34|BBB\n3:ef56|CCC",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "AAA\nBBB\nCCC\n"
        assert "cleanup_applied" in result
        assert "prefix_strip" in result["cleanup_applied"]

    def test_set_line_prefix_not_stripped_single_line(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """set_line with a hashline-prefixed value writes it literally (single-line skip)."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps(
            [{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "5:a3b1|hello"}]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        # Single-line content is never prefix-stripped (by design)
        assert f.read_text() == "5:a3b1|hello\nbbb\n"
        assert "cleanup_applied" not in result

    def test_auto_cleanup_false_preserves_prefix(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """auto_cleanup=False writes literal hashline-prefixed content as-is."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {
                    "op": "replace_lines",
                    "start_anchor": _anchor(1, "aaa"),
                    "end_anchor": _anchor(3, "ccc"),
                    "content": "1:ab12|AAA\n2:cd34|BBB\n3:ef56|CCC",
                }
            ]
        )
        result = hashline_edit_fn(
            path="test.txt", edits=edits, **mock_workspace, auto_cleanup=False
        )

        assert result["success"] is True
        assert f.read_text() == "1:ab12|AAA\n2:cd34|BBB\n3:ef56|CCC\n"
        assert "cleanup_applied" not in result


class TestAtomicityWithReplace:
    """Atomicity: replace op failure after splice leaves file unchanged."""

    def test_replace_sees_post_splice_content(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """replace op matches against content after splices are applied."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        # First op changes line 1 to "AAA", then replace op matches "AAA" -> "ZZZ"
        edits = json.dumps(
            [
                {"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"},
                {"op": "replace", "old_content": "AAA", "new_content": "ZZZ"},
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "ZZZ\nbbb\n"


class TestAtomicWrite:
    """Tests for atomic write behavior."""

    def test_atomic_write_preserves_original_on_write_failure(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """If write fails, the original file is untouched."""
        f = tmp_path / "test.txt"
        original = "aaa\nbbb\n"
        f.write_text(original)

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])

        # Make the directory read-only to force write failure
        import stat

        tmp_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)
            assert "error" in result
            assert f.read_text() == original
        finally:
            tmp_path.chmod(stat.S_IRWXU)


class TestGuardRails:
    """Tests for edit count and file size limits."""

    @pytest.mark.parametrize("count,should_error", [(100, False), (101, True)])
    def test_edit_count_limit(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path, count, should_error
    ):
        """100 edits allowed, 101 rejected."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\n")

        edits = json.dumps(
            [{"op": "set_line", "anchor": "1:0000", "content": "x"} for _ in range(count)]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        if should_error:
            assert "error" in result
            assert "max 100" in result["error"].lower()
        else:
            assert "max 100" not in result.get("error", "").lower()

    @pytest.mark.parametrize("over_limit", [False, True])
    def test_file_size_limit(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path, over_limit
    ):
        """File at exactly 10MB allowed, over 10MB rejected."""
        f = tmp_path / "test.txt"
        size = 10 * 1024 * 1024 + (1 if over_limit else 0)
        f.write_text("x" * size)

        edits = json.dumps([{"op": "replace", "old_content": "x" * 10, "new_content": "y" * 10}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        if over_limit:
            assert "error" in result
            assert "too large" in result["error"].lower()
        else:
            assert "too large" not in result.get("error", "").lower()


class TestInsertBefore:
    """Tests for the insert_before op."""

    def test_insert_before_basic(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_before inserts new lines before the anchor line."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "insert_before", "anchor": _anchor(2, "bbb"), "content": "NEW"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nNEW\nbbb\nccc\n"

    def test_insert_before_first_line(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_before on line 1 prepends content."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps(
            [{"op": "insert_before", "anchor": _anchor(1, "aaa"), "content": "HEADER"}]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "HEADER\naaa\nbbb\n"

    def test_insert_before_multiline(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """insert_before can insert multiple lines."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")

        edits = json.dumps(
            [{"op": "insert_before", "anchor": _anchor(2, "bbb"), "content": "x\ny\nz"}]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nx\ny\nz\nbbb\n"

    def test_two_insert_before_same_anchor(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Two insert_before at the same anchor produce A before B in output."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps(
            [
                {"op": "insert_before", "anchor": _anchor(2, "bbb"), "content": "FIRST"},
                {"op": "insert_before", "anchor": _anchor(2, "bbb"), "content": "SECOND"},
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nFIRST\nSECOND\nbbb\nccc\n"


class TestAppend:
    """Tests for the append op."""

    def test_append_to_empty_file(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """append writes initial content to an empty file."""
        f = tmp_path / "test.txt"
        f.write_text("")

        edits = json.dumps([{"op": "append", "content": "first\nsecond"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "first\nsecond"

    def test_append_to_nonempty_file(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """append adds new lines at the end of a non-empty file."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\nccc\n")

        edits = json.dumps([{"op": "append", "content": "ddd\neee"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "aaa\nbbb\nccc\nddd\neee\n"

    def test_append_strips_hashline_prefixes(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """append strips hashline prefixes when auto_cleanup is enabled."""
        f = tmp_path / "test.txt"
        f.write_text("")

        edits = json.dumps([{"op": "append", "content": "1:ab12|AAA\n2:cd34|BBB"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "AAA\nBBB"
        assert "cleanup_applied" in result
        assert "prefix_strip" in result["cleanup_applied"]

    def test_append_empty_content_rejected(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """append with empty content is rejected."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\n")

        edits = json.dumps([{"op": "append", "content": ""}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "must not be empty" in result["error"]
        assert f.read_text() == "aaa\n"

    def test_append_missing_content_rejected(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """append without content is rejected."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\n")

        edits = json.dumps([{"op": "append"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "missing content" in result["error"]
        assert f.read_text() == "aaa\n"


class TestEncodingParam:
    """Tests for the encoding parameter."""

    def test_encoding_latin1(self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path):
        """encoding='latin-1' reads and writes latin-1 files correctly."""
        f = tmp_path / "test.txt"
        f.write_bytes("caf\xe9\n".encode("latin-1"))

        edits = json.dumps([{"op": "replace", "old_content": "caf\u00e9", "new_content": "tea"}])
        result = hashline_edit_fn(
            path="test.txt", edits=edits, **mock_workspace, encoding="latin-1"
        )

        assert result["success"] is True
        assert f.read_bytes() == b"tea\n"

    def test_encoding_default_utf8(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Default encoding handles standard UTF-8 files."""
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld\n", encoding="utf-8")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "hello"), "content": "HELLO"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "HELLO\nworld\n"

    def test_preserves_crlf_newlines(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Editing a CRLF file should preserve CRLF line endings."""
        f = tmp_path / "test.txt"
        f.write_bytes(b"aaa\r\nbbb\r\nccc\r\n")

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(2, "bbb"), "content": "BBB"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_bytes() == b"aaa\r\nBBB\r\nccc\r\n"


class TestAllowMultiple:
    """Tests for the replace op allow_multiple flag."""

    def test_allow_multiple_replaces_all(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """allow_multiple: true replaces all occurrences."""
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo baz foo\n")

        edits = json.dumps(
            [{"op": "replace", "old_content": "foo", "new_content": "qux", "allow_multiple": True}]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.read_text() == "qux bar qux baz qux\n"
        assert "replacements" in result
        assert result["replacements"]["edit_1"] == 3

    def test_allow_multiple_false_rejects_duplicates(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """allow_multiple: false (default) still rejects multiple matches."""
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo\n")

        edits = json.dumps([{"op": "replace", "old_content": "foo", "new_content": "qux"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "2 times" in result["error"]
        assert f.read_text() == "foo bar foo\n"

    def test_allow_multiple_string_false_rejected(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """allow_multiple: "false" (string) returns type error, not silent truthy replace-all."""
        f = tmp_path / "test.txt"
        f.write_text("foo bar foo\n")

        edits = json.dumps(
            [
                {
                    "op": "replace",
                    "old_content": "foo",
                    "new_content": "qux",
                    "allow_multiple": "false",
                }
            ]
        )
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" in result
        assert "boolean" in result["error"].lower()
        assert f.read_text() == "foo bar foo\n"


class TestPermissionsPreservation:
    """Tests for file permissions preservation during atomic write."""

    @pytest.mark.parametrize("mode", [0o755, 0o644])
    def test_permissions_preserved_after_edit(
        self, hashline_edit_fn, mock_workspace, mock_secure_path, tmp_path, mode
    ):
        """File permissions are preserved after editing."""
        f = tmp_path / "test.txt"
        f.write_text("aaa\nbbb\n")
        f.chmod(mode)

        edits = json.dumps([{"op": "set_line", "anchor": _anchor(1, "aaa"), "content": "AAA"}])
        result = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert result["success"] is True
        assert f.stat().st_mode & 0o777 == mode
