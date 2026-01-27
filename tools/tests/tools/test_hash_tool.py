"""Tests for hash_tool - A cryptographic hash computation tool."""
import pytest

from fastmcp import FastMCP
from aden_tools.tools.hash_tool.hash_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance."""
    return FastMCP("test")


@pytest.fixture
def hash_tool_fn(mcp: FastMCP):
    """Register and return the hash_tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["hash_tool"].fn


class TestHashTool:
    """Tests for hash_tool function."""

    def test_sha256_default(self, hash_tool_fn):
        """Default algorithm is sha256."""
        result = hash_tool_fn(text="hello")

        assert result["algorithm"] == "sha256"
        assert result["hash"] == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert result["length"] == 5

    def test_md5_algorithm(self, hash_tool_fn):
        """MD5 algorithm works correctly."""
        result = hash_tool_fn(text="hello", algorithm="md5")

        assert result["algorithm"] == "md5"
        assert result["hash"] == "5d41402abc4b2a76b9719d911017c592"
        assert result["length"] == 5

    def test_sha1_algorithm(self, hash_tool_fn):
        """SHA1 algorithm works correctly."""
        result = hash_tool_fn(text="hello", algorithm="sha1")

        assert result["algorithm"] == "sha1"
        assert result["hash"] == "aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d"
        assert result["length"] == 5

    def test_sha512_algorithm(self, hash_tool_fn):
        """SHA512 algorithm works correctly."""
        result = hash_tool_fn(text="hello", algorithm="sha512")

        assert result["algorithm"] == "sha512"
        assert "hash" in result
        assert len(result["hash"]) == 128  # SHA512 produces 128 hex chars
        assert result["length"] == 5

    def test_algorithm_case_insensitive(self, hash_tool_fn):
        """Algorithm name is case-insensitive."""
        result_upper = hash_tool_fn(text="test", algorithm="SHA256")
        result_lower = hash_tool_fn(text="test", algorithm="sha256")

        assert result_upper["hash"] == result_lower["hash"]
        assert result_upper["algorithm"] == "sha256"

    def test_algorithm_with_whitespace(self, hash_tool_fn):
        """Algorithm name with whitespace is trimmed."""
        result = hash_tool_fn(text="test", algorithm="  sha256  ")

        assert result["algorithm"] == "sha256"
        assert "hash" in result

    def test_empty_text_error(self, hash_tool_fn):
        """Empty text returns error."""
        result = hash_tool_fn(text="")

        assert "error" in result
        assert "1-100000" in result["error"]

    def test_text_too_long_error(self, hash_tool_fn):
        """Text over 100000 chars returns error."""
        long_text = "x" * 100001
        result = hash_tool_fn(text=long_text)

        assert "error" in result
        assert "1-100000" in result["error"]

    def test_text_at_max_length(self, hash_tool_fn):
        """Text exactly 100000 chars is valid."""
        max_text = "x" * 100000
        result = hash_tool_fn(text=max_text)

        assert "hash" in result
        assert result["length"] == 100000

    def test_invalid_algorithm_error(self, hash_tool_fn):
        """Invalid algorithm returns error."""
        result = hash_tool_fn(text="hello", algorithm="invalid")

        assert "error" in result
        assert "must be one of" in result["error"]

    def test_unicode_text(self, hash_tool_fn):
        """Unicode text is handled correctly."""
        result = hash_tool_fn(text="Hello 世界 🌍")

        assert "hash" in result
        assert result["algorithm"] == "sha256"

    def test_special_characters(self, hash_tool_fn):
        """Special characters are hashed correctly."""
        result = hash_tool_fn(text="!@#$%^&*()_+-=[]{}|;':\",./<>?")

        assert "hash" in result
        assert result["algorithm"] == "sha256"

    def test_whitespace_only_text(self, hash_tool_fn):
        """Whitespace-only text is valid."""
        result = hash_tool_fn(text="   ")

        assert "hash" in result
        assert result["length"] == 3

    def test_newlines_in_text(self, hash_tool_fn):
        """Newlines in text are hashed correctly."""
        result = hash_tool_fn(text="line1\nline2\nline3")

        assert "hash" in result
        assert result["length"] == 17

    def test_deterministic_output(self, hash_tool_fn):
        """Same input always produces same hash."""
        result1 = hash_tool_fn(text="consistent")
        result2 = hash_tool_fn(text="consistent")

        assert result1["hash"] == result2["hash"]

    def test_different_inputs_different_hashes(self, hash_tool_fn):
        """Different inputs produce different hashes."""
        result1 = hash_tool_fn(text="hello")
        result2 = hash_tool_fn(text="world")

        assert result1["hash"] != result2["hash"]
