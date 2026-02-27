"""Unit tests for the hashline utility module."""

import pytest

from aden_tools.tools.file_system_toolkits.hashline import (
    compute_line_hash,
    format_hashlines,
    parse_anchor,
    validate_anchor,
)


class TestComputeLineHash:
    """Tests for compute_line_hash."""

    def test_basic_output_format(self):
        """Hash is a 4-char lowercase hex string."""
        h = compute_line_hash("hello world")
        assert len(h) == 4
        assert all(c in "0123456789abcdef" for c in h)

    def test_space_stripping(self):
        """Trailing spaces are stripped before hashing."""
        assert compute_line_hash("hello  ") == compute_line_hash("hello")
        assert compute_line_hash("  hello") != compute_line_hash("hello")

    def test_tab_stripping(self):
        """Trailing tabs are stripped before hashing."""
        assert compute_line_hash("hello\t") == compute_line_hash("hello")
        assert compute_line_hash("\thello") != compute_line_hash("hello")

    def test_empty_line(self):
        """Empty line produces a valid 4-char hash."""
        h = compute_line_hash("")
        assert len(h) == 4
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_lines_different_hashes(self):
        """Different lines produce different hashes (most of the time)."""
        h1 = compute_line_hash("def foo():")
        h2 = compute_line_hash("def bar():")
        # These specific strings should produce different hashes
        assert h1 != h2

    def test_whitespace_only_equals_empty(self):
        """A line of only spaces/tabs hashes the same as empty."""
        assert compute_line_hash("   \t  ") == compute_line_hash("")

    def test_formatter_resilience(self):
        """Trailing whitespace-only variants stay stable across formatting noise."""
        assert compute_line_hash("if x:") == compute_line_hash("if x:   ")
        assert compute_line_hash("return 0") == compute_line_hash("return 0\t\t")

    def test_leading_whitespace_changes_hash(self):
        """Leading whitespace changes the hash (indentation is semantic)."""
        assert compute_line_hash("  x") != compute_line_hash("    x")

    def test_trailing_whitespace_ignored(self):
        """Trailing spaces are ignored in hashing."""
        assert compute_line_hash("x  ") == compute_line_hash("x")


class TestFormatHashlines:
    """Tests for format_hashlines."""

    def test_basic_format(self):
        """Lines are formatted as N:hhhh|content."""
        lines = ["hello", "world"]
        result = format_hashlines(lines)
        output_lines = result.split("\n")
        assert len(output_lines) == 2
        # Check format: N:hhhh|content
        assert output_lines[0].startswith("1:")
        assert "|hello" in output_lines[0]
        assert output_lines[1].startswith("2:")
        assert "|world" in output_lines[1]

    def test_offset(self):
        """Offset skips initial lines."""
        lines = ["a", "b", "c", "d"]
        result = format_hashlines(lines, offset=3)
        output_lines = result.split("\n")
        assert len(output_lines) == 2
        assert output_lines[0].startswith("3:")
        assert "|c" in output_lines[0]

    def test_limit(self):
        """Limit restricts number of lines returned."""
        lines = ["a", "b", "c", "d"]
        result = format_hashlines(lines, limit=2)
        output_lines = result.split("\n")
        assert len(output_lines) == 2
        assert "|a" in output_lines[0]
        assert "|b" in output_lines[1]

    def test_offset_and_limit(self):
        """Offset and limit work together."""
        lines = ["a", "b", "c", "d", "e"]
        result = format_hashlines(lines, offset=2, limit=2)
        output_lines = result.split("\n")
        assert len(output_lines) == 2
        assert output_lines[0].startswith("2:")
        assert "|b" in output_lines[0]
        assert output_lines[1].startswith("3:")
        assert "|c" in output_lines[1]

    def test_empty_input(self):
        """Empty input produces empty output."""
        result = format_hashlines([])
        assert result == ""


class TestParseAnchor:
    """Tests for parse_anchor."""

    def test_valid_anchor(self):
        """Valid anchor is parsed correctly."""
        line_num, hash_str = parse_anchor("5:a3b1")
        assert line_num == 5
        assert hash_str == "a3b1"

    def test_valid_anchor_with_zeros(self):
        """Anchor with zero-padded hash works."""
        line_num, hash_str = parse_anchor("1:0000")
        assert line_num == 1
        assert hash_str == "0000"

    def test_no_colon(self):
        """Missing colon raises ValueError."""
        with pytest.raises(ValueError, match="no colon"):
            parse_anchor("5a3")

    @pytest.mark.parametrize("bad_anchor", ["5:abc", "5:a", "5:abcd1234"])
    def test_wrong_hash_length(self, bad_anchor):
        """Hash with wrong length raises ValueError."""
        with pytest.raises(ValueError, match="4 chars"):
            parse_anchor(bad_anchor)

    def test_uppercase_hash(self):
        """Uppercase hex raises ValueError."""
        with pytest.raises(ValueError, match="lowercase hex"):
            parse_anchor("5:A3B1")

    def test_non_hex_hash(self):
        """Non-hex chars in hash raises ValueError."""
        with pytest.raises(ValueError, match="lowercase hex"):
            parse_anchor("5:zzxx")

    def test_non_integer_line(self):
        """Non-integer line number raises ValueError."""
        with pytest.raises(ValueError, match="not an integer"):
            parse_anchor("abc:a3b1")


class TestValidateAnchor:
    """Tests for validate_anchor."""

    def test_valid_match(self):
        """Valid anchor returns None."""
        lines = ["hello", "world"]
        h = compute_line_hash("hello")
        assert validate_anchor(f"1:{h}", lines) is None

    def test_hash_mismatch(self):
        """Mismatched hash returns error with re-read hint and current content."""
        lines = ["hello", "world"]
        err = validate_anchor("1:ffff", lines)
        assert err is not None
        assert "mismatch" in err.lower()
        assert "re-read" in err.lower()
        assert "hello" in err

    @pytest.mark.parametrize("anchor", ["5:abcd", "0:0000"])
    def test_out_of_range(self, anchor):
        """Line number beyond file length or zero returns error."""
        lines = ["hello"]
        err = validate_anchor(anchor, lines)
        assert err is not None
        assert "out of range" in err.lower()

    def test_invalid_format(self):
        """Invalid anchor format returns error."""
        lines = ["hello"]
        err = validate_anchor("bad", lines)
        assert err is not None
        assert "no colon" in err.lower()
